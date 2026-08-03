"""Real Live View streaming: blinkpy's own local relay, remuxed to HLS.

``BlinkService.init_live_stream()`` hands back a running local TCP relay
(see ``app.blink.service.BlinkLiveStreamHandle``) that re-streams Blink's
proprietary IMMI payload as plain MPEG-TS once a client connects. ffmpeg is
that one client: it reads the relay's ``tcp://`` URL and remuxes it into a
short-segment HLS playlist on local disk, which is what a browser's
video.js player actually consumes.

blinkpy's relay polls Blink's command-status API for as long as the session
runs (``BlinkLiveStream.poll()``, reached via ``self.camera.sync.blink`` —
the very same ``Blink``/``Auth`` instance the owning ``BlinkPyService``
holds) — so, unlike ``get_camera_preview()``/``record_camera_clip()``, the
``BlinkPyService`` passed to :meth:`LiveViewSessionManager.start_session`
must stay open for the session's whole lifetime, not just the initial
request. The manager takes ownership of it at that point and closes it on
teardown, whichever path (explicit stop, idle sweep, app shutdown)
triggers it.
"""

import asyncio
import contextlib
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from app.blink.service import BlinkLiveStreamHandle
from app.logs import get_logger

logger = get_logger(__name__)


class ClosableBlinkService(Protocol):
    """Everything this module actually needs from a BlinkService - just the
    ability to close it once the session ends, not the full protocol (a
    BlinkPyService satisfies this trivially; tests don't need to fake seven
    unrelated methods just to construct one)."""

    async def close(self) -> None: ...


SESSION_IDLE_TIMEOUT = timedelta(seconds=60)
"""No playlist/segment request in this long -> the browser tab most likely
closed or navigated away without calling the stop endpoint - swept
automatically so an abandoned session doesn't leak an ffmpeg process and a
relay socket forever."""
SWEEP_INTERVAL_SECONDS = 15
FFMPEG_START_TIMEOUT_SECONDS = 10
"""How long to wait for ffmpeg to write the first playlist file before
declaring the session failed - a camera that negotiates immis:// but then
never actually sends video would otherwise hang "starting" forever."""
PROCESS_STOP_TIMEOUT_SECONDS = 5
"""How long to give ffmpeg to exit after terminate() before escalating to
kill()."""
FEED_TASK_STOP_TIMEOUT_SECONDS = 5
"""How long to give blinkpy's relay to wind down after handle.stop() before
this gives up waiting and cancels it directly."""

HLS_SEGMENT_SECONDS = 2
HLS_LIST_SIZE = 6
PLAYLIST_FILENAME = "stream.m3u8"
_SEGMENT_NAME_RE = re.compile(r"^segment\d{5}\.ts$")


class LiveViewStartError(Exception):
    """ffmpeg could not be started, or never produced a playable playlist."""


def _log_feed_task_error(task: asyncio.Task[None]) -> None:
    """Retrieves feed_task's result so an error inside blinkpy's own relay
    (e.g. its auth() step failing before feed()'s internal try/except even
    starts) surfaces in our logs instead of asyncio's generic "exception was
    never retrieved" warning at garbage-collection time."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.warning("live_view.feed_task_error", error=str(exc))


def _tail_log(temp_dir: Path, max_bytes: int = 2000) -> str:
    # _spawn_ffmpeg() always creates this file (opening it for write is what
    # happens before the subprocess call that might fail) before this is
    # ever reachable - see _wait_for_playlist's only call site below.
    data = (temp_dir / "ffmpeg.log").read_bytes()[-max_bytes:]
    return data.decode(errors="replace").strip() or "(empty ffmpeg output)"


@dataclass
class LiveViewSession:
    session_id: uuid.UUID
    camera_id: uuid.UUID
    service: ClosableBlinkService
    handle: BlinkLiveStreamHandle
    process: asyncio.subprocess.Process
    temp_dir: Path
    feed_task: asyncio.Task[None]
    last_accessed_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def playlist_path(self) -> Path:
        return self.temp_dir / PLAYLIST_FILENAME

    def touch(self) -> None:
        self.last_accessed_at = datetime.now(UTC)

    @property
    def idle(self) -> bool:
        return datetime.now(UTC) - self.last_accessed_at > SESSION_IDLE_TIMEOUT


class LiveViewSessionStarter(Protocol):
    """What app.livefeed.service.start_live_view() actually needs from a
    manager - lets that function's tests fake this one method instead of
    driving a real LiveViewSessionManager (ffmpeg lifecycle and all)."""

    async def start_session(
        self, camera_id: uuid.UUID, service: ClosableBlinkService, handle: BlinkLiveStreamHandle
    ) -> LiveViewSession: ...


class LiveViewSessionManager:
    """Owned by ``app.state`` — one per running API process.

    Unlike ``BlinkLinker``'s lazy sweep-on-access (cheap to leak - a bare
    ``Auth`` object), a leaked session here is an ffmpeg subprocess plus an
    open relay socket, so this runs a genuine periodic background sweep
    rather than waiting for the next request to notice - lazily started on
    the first session, so a household that never opens Live View pays
    nothing for it.
    """

    def __init__(self) -> None:
        self._sessions: dict[uuid.UUID, LiveViewSession] = {}
        self._by_camera: dict[uuid.UUID, uuid.UUID] = {}
        self._sweeper: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    async def _sweep_loop(self) -> None:
        while True:
            await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
            idle = [s for s in self._sessions.values() if s.idle]
            for session in idle:
                logger.info("live_view.session_idle_timeout", session_id=str(session.session_id))
                await self._stop(session)

    async def start_session(
        self, camera_id: uuid.UUID, service: ClosableBlinkService, handle: BlinkLiveStreamHandle
    ) -> LiveViewSession:
        """Takes ownership of ``service``/``handle``: from this call
        onward, the manager is solely responsible for closing them,
        including if this method itself raises."""
        async with self._lock:
            if self._sweeper is None:
                self._sweeper = asyncio.create_task(self._sweep_loop())

            # _sessions/_by_camera are only ever mutated together (here and
            # in _stop()), so a camera_id present in _by_camera always has
            # a matching entry in _sessions - indexing directly rather than
            # re-checking an invariant this class itself guarantees.
            existing_id = self._by_camera.get(camera_id)
            if existing_id is not None:
                await self._stop(self._sessions[existing_id])

            feed_task = asyncio.create_task(handle.feed())
            feed_task.add_done_callback(_log_feed_task_error)
            temp_dir = Path(tempfile.mkdtemp(prefix="live-view-"))
            try:
                process = await self._spawn_ffmpeg(handle.url, temp_dir)
            except LiveViewStartError:
                # No session object exists yet (nothing to hand to _stop) -
                # the same cleanup, minus killing a process that was never
                # spawned.
                handle.stop()
                feed_task.cancel()
                shutil.rmtree(temp_dir, ignore_errors=True)
                await service.close()
                raise

            session = LiveViewSession(
                session_id=uuid.uuid4(),
                camera_id=camera_id,
                service=service,
                handle=handle,
                process=process,
                temp_dir=temp_dir,
                feed_task=feed_task,
            )
            try:
                await self._wait_for_playlist(session)
            except LiveViewStartError:
                await self._stop(session)
                raise
            self._sessions[session.session_id] = session
            self._by_camera[camera_id] = session.session_id
            logger.info(
                "live_view.session_started",
                session_id=str(session.session_id),
                camera_id=str(camera_id),
            )
            return session

    async def _spawn_ffmpeg(self, source_url: str, temp_dir: Path) -> asyncio.subprocess.Process:
        args = [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-fflags",
            "+genpts+discardcorrupt",
            "-f",
            "mpegts",
            "-i",
            source_url,
            "-c",
            "copy",
            "-f",
            "hls",
            "-hls_time",
            str(HLS_SEGMENT_SECONDS),
            "-hls_list_size",
            str(HLS_LIST_SIZE),
            "-hls_flags",
            "delete_segments+omit_endlist",
            "-hls_segment_filename",
            str(temp_dir / "segment%05d.ts"),
            str(temp_dir / PLAYLIST_FILENAME),
        ]
        # A long-running process writing to a pipe risks blocking on a full
        # kernel buffer if nothing drains it - a plain file has no such
        # ceiling, and _tail_log() reads it back only if something actually
        # goes wrong. Our own copy of the fd is safely closeable right after
        # spawn: the child holds its own dup'd fd into the same open file.
        log_path = temp_dir / "ffmpeg.log"
        with log_path.open("wb") as log_file:
            try:
                return await asyncio.create_subprocess_exec(
                    *args, stdout=asyncio.subprocess.DEVNULL, stderr=log_file
                )
            except OSError as exc:
                raise LiveViewStartError(f"could not start ffmpeg: {exc}") from exc

    async def _wait_for_playlist(self, session: LiveViewSession) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + FFMPEG_START_TIMEOUT_SECONDS
        while loop.time() < deadline:
            if session.process.returncode is not None:
                raise LiveViewStartError(
                    f"ffmpeg exited before producing a playlist: {_tail_log(session.temp_dir)}"
                )
            if session.playlist_path.exists():
                return
            await asyncio.sleep(0.2)
        raise LiveViewStartError("Timed out waiting for the live stream to start.")

    def get(self, session_id: uuid.UUID) -> LiveViewSession | None:
        return self._sessions.get(session_id)

    def get_file(self, session_id: uuid.UUID, filename: str) -> Path | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if filename != PLAYLIST_FILENAME and not _SEGMENT_NAME_RE.fullmatch(filename):
            return None
        path = session.temp_dir / filename
        if not path.exists():
            return None
        session.touch()
        return path

    async def stop_session(self, session_id: uuid.UUID) -> None:
        session = self._sessions.get(session_id)
        if session is not None:
            await self._stop(session)

    async def _stop(self, session: LiveViewSession) -> None:
        self._sessions.pop(session.session_id, None)
        if self._by_camera.get(session.camera_id) == session.session_id:
            del self._by_camera[session.camera_id]

        if session.process.returncode is None:
            session.process.terminate()
            try:
                await asyncio.wait_for(session.process.wait(), timeout=PROCESS_STOP_TIMEOUT_SECONDS)
            except TimeoutError:
                # The process can still have exited in the gap between the
                # timeout firing and this line - kill() raises
                # ProcessLookupError for an already-dead process, which is a
                # normal outcome here, not a failure.
                with contextlib.suppress(ProcessLookupError):
                    session.process.kill()
                await session.process.wait()

        # Idempotent even if feed() already returned on its own (e.g. ffmpeg
        # disconnecting made blinkpy's relay self-stop first).
        session.handle.stop()
        # Broad by design: wait_for() cancels feed_task on timeout and
        # awaits its settling either way, so this always leaves feed_task
        # done - suppressing Exception here covers both a plain TimeoutError
        # and feed_task's own exception (already reported by
        # _log_feed_task_error) being re-raised from awaiting it.
        with contextlib.suppress(Exception):
            await asyncio.wait_for(session.feed_task, timeout=FEED_TASK_STOP_TIMEOUT_SECONDS)

        await session.service.close()
        shutil.rmtree(session.temp_dir, ignore_errors=True)
        logger.info("live_view.session_stopped", session_id=str(session.session_id))

    async def aclose(self) -> None:
        if self._sweeper is not None:
            self._sweeper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._sweeper
        for session in list(self._sessions.values()):
            await self._stop(session)
