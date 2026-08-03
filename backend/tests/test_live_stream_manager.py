"""LiveViewSessionManager: ffmpeg lifecycle + session bookkeeping.

ffmpeg itself is faked (patched at ``asyncio.create_subprocess_exec``, same
convention as test_ffmpeg.py's error-path tests) rather than run for real -
this module orchestrates a *subprocess's lifecycle*, not ffmpeg's actual
media handling, and the fake relay's ``url`` isn't a real listening socket
for a real ffmpeg to connect to anyway.

A real BlinkLiveStreamHandle wraps a fake relay (rather than a hand-rolled
duck-typed fake) - it's already designed as a thin, real, publicly
constructable adapter (see its own docstring), so there's nothing to gain
from re-inventing a parallel fake type for it.
"""

# pytest calls autouse fixtures implicitly; pyright can't see that usage.
# pyright: reportUnusedFunction=false

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import timedelta
from pathlib import Path

import pytest

from app.blink.service import BlinkLiveStreamHandle
from app.livefeed.live_stream import LiveViewSessionManager, LiveViewStartError


class FakeProcess:
    def __init__(self) -> None:
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False
        self._exited = asyncio.Event()

    async def wait(self) -> int:
        await self._exited.wait()
        assert self.returncode is not None
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        if self.returncode is None:
            self.returncode = 0
        self._exited.set()

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9
        self._exited.set()

    def exit_now(self, code: int) -> None:
        """Simulates the child exiting on its own (crash, bad input)."""
        self.returncode = code
        self._exited.set()


class FakeRelay:
    """Backs a real BlinkLiveStreamHandle so the manager under test always
    sees a genuine handle instance, matching production."""

    def __init__(self, url: str = "tcp://127.0.0.1:9999") -> None:
        self.url = url
        self.stopped = False
        self.feed_calls = 0
        self.feed_error: Exception | None = None

    async def feed(self) -> None:
        self.feed_calls += 1
        if self.feed_error:
            raise self.feed_error

    def stop(self) -> None:
        self.stopped = True


def make_handle(feed_error: Exception | None = None) -> tuple[BlinkLiveStreamHandle, FakeRelay]:
    relay = FakeRelay()
    relay.feed_error = feed_error
    handle = BlinkLiveStreamHandle(url=relay.url, feed=relay.feed, stop=relay.stop)
    return handle, relay


class FakeService:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


_FakeExec = Callable[..., Awaitable[FakeProcess]]


def _writes_playlist(process_holder: list[FakeProcess]) -> _FakeExec:
    async def fake_exec(*args: str, **_kwargs: object) -> FakeProcess:
        Path(args[-1]).write_text("#EXTM3U\n")
        process = FakeProcess()
        process_holder.append(process)
        return process

    return fake_exec


def _exits_immediately(code: int, process_holder: list[FakeProcess]) -> _FakeExec:
    async def fake_exec(*_args: str, **_kwargs: object) -> FakeProcess:
        process = FakeProcess()
        process.exit_now(code)
        process_holder.append(process)
        return process

    return fake_exec


def _never_produces_output(process_holder: list[FakeProcess]) -> _FakeExec:
    async def fake_exec(*_args: str, **_kwargs: object) -> FakeProcess:
        process = FakeProcess()
        process_holder.append(process)
        return process

    return fake_exec


@pytest.fixture
async def manager() -> AsyncIterator[LiveViewSessionManager]:
    mgr = LiveViewSessionManager()
    yield mgr
    await mgr.aclose()


async def test_start_session_spawns_ffmpeg_and_returns_a_playlist_path(
    manager: LiveViewSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    processes: list[FakeProcess] = []
    monkeypatch.setattr("asyncio.create_subprocess_exec", _writes_playlist(processes))
    camera_id = uuid.uuid4()
    handle, relay = make_handle()
    service = FakeService()

    session = await manager.start_session(camera_id, service, handle)
    await asyncio.sleep(0)  # let the already-scheduled feed_task actually run once

    assert session.camera_id == camera_id
    assert session.playlist_path.exists()
    assert manager.get(session.session_id) is session
    assert relay.feed_calls == 1


async def test_start_session_raises_when_ffmpeg_exits_immediately(
    manager: LiveViewSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    processes: list[FakeProcess] = []
    monkeypatch.setattr("asyncio.create_subprocess_exec", _exits_immediately(1, processes))
    handle, relay = make_handle()
    service = FakeService()

    with pytest.raises(LiveViewStartError, match="ffmpeg exited"):
        await manager.start_session(uuid.uuid4(), service, handle)

    assert relay.stopped is True
    assert service.closed is True


async def test_start_session_times_out_when_ffmpeg_never_produces_a_playlist(
    manager: LiveViewSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.livefeed.live_stream.FFMPEG_START_TIMEOUT_SECONDS", 0.3)
    processes: list[FakeProcess] = []
    monkeypatch.setattr("asyncio.create_subprocess_exec", _never_produces_output(processes))
    handle, relay = make_handle()
    service = FakeService()

    with pytest.raises(LiveViewStartError, match="Timed out"):
        await manager.start_session(uuid.uuid4(), service, handle)

    assert processes[0].terminated is True
    assert relay.stopped is True
    assert service.closed is True


async def test_start_session_raises_when_ffmpeg_binary_is_missing(
    manager: LiveViewSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_exec(*_args: str, **_kwargs: object) -> FakeProcess:
        raise FileNotFoundError("no such file: ffmpeg")

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    handle, relay = make_handle()
    service = FakeService()

    with pytest.raises(LiveViewStartError, match="could not start ffmpeg"):
        await manager.start_session(uuid.uuid4(), service, handle)

    assert relay.stopped is True
    assert service.closed is True


async def test_starting_a_second_session_for_the_same_camera_stops_the_first(
    manager: LiveViewSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    processes: list[FakeProcess] = []
    monkeypatch.setattr("asyncio.create_subprocess_exec", _writes_playlist(processes))
    camera_id = uuid.uuid4()
    first_handle, first_relay = make_handle()
    second_handle, _second_relay = make_handle()
    first_service, second_service = FakeService(), FakeService()

    first = await manager.start_session(camera_id, first_service, first_handle)
    second = await manager.start_session(camera_id, second_service, second_handle)

    assert manager.get(first.session_id) is None
    assert first_relay.stopped is True
    assert first_service.closed is True
    assert manager.get(second.session_id) is second


async def test_get_file_returns_none_for_an_unknown_session(
    manager: LiveViewSessionManager,
) -> None:
    assert manager.get_file(uuid.uuid4(), "stream.m3u8") is None


async def test_get_file_rejects_a_filename_outside_the_allowlist(
    manager: LiveViewSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    processes: list[FakeProcess] = []
    monkeypatch.setattr("asyncio.create_subprocess_exec", _writes_playlist(processes))
    handle, _relay = make_handle()
    session = await manager.start_session(uuid.uuid4(), FakeService(), handle)

    assert manager.get_file(session.session_id, "../../etc/passwd") is None
    assert manager.get_file(session.session_id, "not-a-real-file.ts") is None


async def test_get_file_returns_the_playlist_and_touches_the_session(
    manager: LiveViewSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    processes: list[FakeProcess] = []
    monkeypatch.setattr("asyncio.create_subprocess_exec", _writes_playlist(processes))
    handle, _relay = make_handle()
    session = await manager.start_session(uuid.uuid4(), FakeService(), handle)
    stale = session.last_accessed_at

    path = manager.get_file(session.session_id, "stream.m3u8")

    assert path == session.playlist_path
    assert session.last_accessed_at >= stale


async def test_get_file_serves_a_segment_that_exists(
    manager: LiveViewSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    processes: list[FakeProcess] = []
    monkeypatch.setattr("asyncio.create_subprocess_exec", _writes_playlist(processes))
    handle, _relay = make_handle()
    session = await manager.start_session(uuid.uuid4(), FakeService(), handle)
    segment = session.temp_dir / "segment00001.ts"
    segment.write_bytes(b"ts-bytes")

    assert manager.get_file(session.session_id, "segment00001.ts") == segment


async def test_get_file_returns_none_for_a_segment_not_yet_written(
    manager: LiveViewSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """segment00099.ts matches the allowlist pattern but was never written -
    e.g. requested before ffmpeg gets there, or already rotated out by
    -hls_flags delete_segments."""
    processes: list[FakeProcess] = []
    monkeypatch.setattr("asyncio.create_subprocess_exec", _writes_playlist(processes))
    handle, _relay = make_handle()
    session = await manager.start_session(uuid.uuid4(), FakeService(), handle)

    assert manager.get_file(session.session_id, "segment00099.ts") is None


async def test_stop_session_is_a_no_op_for_an_unknown_id(
    manager: LiveViewSessionManager,
) -> None:
    await manager.stop_session(uuid.uuid4())  # must not raise


async def test_stop_session_terminates_ffmpeg_closes_the_service_and_removes_the_temp_dir(
    manager: LiveViewSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    processes: list[FakeProcess] = []
    monkeypatch.setattr("asyncio.create_subprocess_exec", _writes_playlist(processes))
    handle, relay = make_handle()
    service = FakeService()
    session = await manager.start_session(uuid.uuid4(), service, handle)
    temp_dir = session.temp_dir

    await manager.stop_session(session.session_id)

    assert processes[0].terminated is True
    assert relay.stopped is True
    assert service.closed is True
    assert not temp_dir.exists()
    assert manager.get(session.session_id) is None


async def test_stop_kills_ffmpeg_if_it_ignores_terminate(
    manager: LiveViewSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    processes: list[FakeProcess] = []

    async def fake_exec(*args: str, **_kwargs: object) -> FakeProcess:
        Path(args[-1]).write_text("#EXTM3U\n")

        class StubbornProcess(FakeProcess):
            def terminate(self) -> None:
                self.terminated = True  # deliberately doesn't set returncode

        process = StubbornProcess()
        processes.append(process)
        return process

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    handle, _relay = make_handle()
    session = await manager.start_session(uuid.uuid4(), FakeService(), handle)

    await manager.stop_session(session.session_id)

    assert processes[0].terminated is True
    assert processes[0].killed is True


async def test_stop_tolerates_the_process_exiting_right_before_kill(
    manager: LiveViewSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A process that exits on its own in the gap between the terminate()
    timeout firing and kill() being called makes kill() raise
    ProcessLookupError - a normal outcome here, not a failure that should
    abort the rest of teardown."""
    processes: list[FakeProcess] = []

    async def fake_exec(*args: str, **_kwargs: object) -> FakeProcess:
        Path(args[-1]).write_text("#EXTM3U\n")

        class DiesJustBeforeKill(FakeProcess):
            def terminate(self) -> None:
                self.terminated = True  # deliberately doesn't set returncode

            def kill(self) -> None:
                self.killed = True
                self.returncode = -9
                self._exited.set()
                raise ProcessLookupError

        process = DiesJustBeforeKill()
        processes.append(process)
        return process

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    handle, relay = make_handle()
    service = FakeService()
    session = await manager.start_session(uuid.uuid4(), service, handle)

    await manager.stop_session(session.session_id)  # must not raise

    assert processes[0].terminated is True
    assert processes[0].killed is True
    assert relay.stopped is True
    assert service.closed is True


async def test_stop_force_cancels_a_feed_task_that_never_finishes(
    manager: LiveViewSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A relay whose feed() doesn't wind down promptly after stop() (unlike
    blinkpy's real one) must still be force-cancelled rather than leaking
    the session's teardown forever."""
    monkeypatch.setattr("app.livefeed.live_stream.FEED_TASK_STOP_TIMEOUT_SECONDS", 0.05)
    processes: list[FakeProcess] = []
    monkeypatch.setattr("asyncio.create_subprocess_exec", _writes_playlist(processes))

    async def hangs_forever() -> None:
        await asyncio.Event().wait()

    handle = BlinkLiveStreamHandle(
        url="tcp://127.0.0.1:9999", feed=hangs_forever, stop=lambda: None
    )
    session = await manager.start_session(uuid.uuid4(), FakeService(), handle)

    await manager.stop_session(session.session_id)

    assert session.feed_task.done() is True


async def test_idle_sessions_are_swept_automatically(
    manager: LiveViewSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.livefeed.live_stream.SWEEP_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr("app.livefeed.live_stream.SESSION_IDLE_TIMEOUT", timedelta(seconds=0))
    processes: list[FakeProcess] = []
    monkeypatch.setattr("asyncio.create_subprocess_exec", _writes_playlist(processes))
    handle, _relay = make_handle()
    session = await manager.start_session(uuid.uuid4(), FakeService(), handle)

    for _ in range(50):
        await asyncio.sleep(0.05)
        if manager.get(session.session_id) is None:
            break

    assert manager.get(session.session_id) is None


async def test_feed_task_exception_is_retrieved_not_left_dangling(
    manager: LiveViewSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A feed() that raises (e.g. blinkpy's auth() step failing) must not
    produce an "exception was never retrieved" warning at GC time - the
    manager's done-callback must consume it, and teardown must still
    complete cleanly. ffmpeg still won't see a playlist, so this reaches
    the ordinary timeout failure path."""
    monkeypatch.setattr("app.livefeed.live_stream.FFMPEG_START_TIMEOUT_SECONDS", 0.3)
    processes: list[FakeProcess] = []
    monkeypatch.setattr("asyncio.create_subprocess_exec", _never_produces_output(processes))
    handle, _relay = make_handle(feed_error=ConnectionRefusedError("blink refused the connection"))
    service = FakeService()

    with pytest.raises(LiveViewStartError, match="Timed out"):
        await manager.start_session(uuid.uuid4(), service, handle)

    assert service.closed is True


async def test_aclose_stops_every_session(monkeypatch: pytest.MonkeyPatch) -> None:
    processes: list[FakeProcess] = []
    monkeypatch.setattr("asyncio.create_subprocess_exec", _writes_playlist(processes))
    manager = LiveViewSessionManager()
    handle, relay = make_handle()
    service = FakeService()
    session = await manager.start_session(uuid.uuid4(), service, handle)

    await manager.aclose()

    assert manager.get(session.session_id) is None
    assert relay.stopped is True
    assert service.closed is True


async def test_aclose_is_safe_when_no_session_was_ever_started() -> None:
    manager = LiveViewSessionManager()
    await manager.aclose()  # must not raise
