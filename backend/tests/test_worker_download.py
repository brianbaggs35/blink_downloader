"""download_clip: fetch, store, probe metadata, and every early-exit/error path.

BlinkPyService is faked (patched at the name imported into
app.worker.tasks.download). The happy path uses a real ffmpeg-synthesized
clip (not arbitrary bytes) so duration/thumbnail generation is genuinely
exercised, not just assumed to work.
"""

# pytest calls autouse fixtures implicitly; pyright can't see that usage.
# pyright: reportUnusedFunction=false

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.blink.models import BlinkAccount, BlinkAccountStatus, Camera, Clip, StorageBackend
from app.blink.service import BlinkAuthError, BlinkError
from app.config import get_settings
from app.integrations.schemas import StorageIntegrationSettingsUpdate
from app.integrations.service import update_storage_integration_settings
from app.security.crypto import SecretBox
from app.settings.service import set_storage_dir
from app.worker.tasks.analyze import ANALYZE_JOB_NAME
from app.worker.tasks.archive import ARCHIVE_CLIP_JOB_NAME, AUTO_ARCHIVE_CLIP_JOB_NAME
from app.worker.tasks.download import download_clip


class FakeBlinkService:
    next_bytes: ClassVar[bytes] = b""
    next_error: ClassVar[Exception | None] = None
    instances: ClassVar[list[FakeBlinkService]] = []

    def __init__(self, token_data: dict[str, Any]) -> None:
        self.token_data_in = dict(token_data)
        self.closed = False
        FakeBlinkService.instances.append(self)

    async def download_media(self, item: Any) -> bytes:
        if FakeBlinkService.next_error:
            raise FakeBlinkService.next_error
        return FakeBlinkService.next_bytes

    async def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_fake_service(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeBlinkService.instances = []
    FakeBlinkService.next_bytes = b""
    FakeBlinkService.next_error = None
    monkeypatch.setattr("app.worker.tasks.download.BlinkPyService", FakeBlinkService)


@pytest.fixture(scope="module")
def synthetic_clip_bytes(tmp_path_factory: pytest.TempPathFactory) -> bytes:
    path = tmp_path_factory.mktemp("src") / "sample.mp4"

    async def make() -> None:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=2:size=64x64:rate=10",
            "-pix_fmt",
            "yuv420p",
            str(path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate()

    asyncio.run(make())
    return path.read_bytes()


async def _make_account_camera_clip(
    session: AsyncSession, *, camera_enabled: bool = True, downloaded: bool = False
) -> tuple[BlinkAccount, Camera, Clip]:
    box = SecretBox(get_settings().encryption_key)
    account = BlinkAccount(
        encrypted_username=box.encrypt("brian@example.com"),
        encrypted_password=box.encrypt("hunter2"),
        encrypted_token_data=box.encrypt(json.dumps({"refresh_token": "r"})),
    )
    session.add(account)
    await session.flush()

    camera = Camera(
        blink_account_id=account.id,
        blink_camera_id="cam-1",
        blink_network_id="net-1",
        name="Front Door",
        camera_type="catalina",
        enabled=camera_enabled,
    )
    session.add(camera)
    await session.flush()

    clip = Clip(
        camera_id=camera.id,
        blink_clip_id="/media/clip1.mp4",
        recorded_at=datetime(2026, 7, 20, tzinfo=UTC),
        raw_metadata={},
        downloaded_at=datetime.now(UTC) if downloaded else None,
    )
    session.add(clip)
    await session.commit()
    await session.refresh(account)
    await session.refresh(camera)
    await session.refresh(clip)
    return account, camera, clip


async def test_clip_not_found_is_a_clean_noop(worker_ctx: dict[str, Any]) -> None:
    result = await download_clip(worker_ctx, str(uuid.uuid4()))
    assert result == "clip_not_found"


async def test_already_downloaded_short_circuits(worker_ctx: dict[str, Any]) -> None:
    async with worker_ctx["sessionmaker"]() as session:
        _account, _camera, clip = await _make_account_camera_clip(session, downloaded=True)
        clip_id = clip.id

    result = await download_clip(worker_ctx, str(clip_id))
    assert result == "already_downloaded"
    assert FakeBlinkService.instances == []  # never even tried to fetch
    worker_ctx["redis"].enqueue_job.assert_not_awaited()


async def test_disabled_camera_is_skipped(worker_ctx: dict[str, Any]) -> None:
    async with worker_ctx["sessionmaker"]() as session:
        _account, _camera, clip = await _make_account_camera_clip(session, camera_enabled=False)
        clip_id = clip.id

    result = await download_clip(worker_ctx, str(clip_id))
    assert result == "camera_disabled_or_missing"


async def test_successful_download_populates_metadata(
    worker_ctx: dict[str, Any], tmp_path: Path, synthetic_clip_bytes: bytes
) -> None:
    async with worker_ctx["sessionmaker"]() as session:
        await set_storage_dir(session, str(tmp_path))
        _account, camera, clip = await _make_account_camera_clip(session)
        clip_id, camera_id = clip.id, camera.id

    FakeBlinkService.next_bytes = synthetic_clip_bytes
    result = await download_clip(worker_ctx, str(clip_id))
    assert result == "ok"

    async with worker_ctx["sessionmaker"]() as session:
        clip = await session.get(Clip, clip_id)
        assert clip is not None
        assert clip.downloaded_at is not None
        assert clip.file_size_bytes == len(synthetic_clip_bytes)
        assert clip.duration_seconds is not None
        assert 1.8 <= clip.duration_seconds <= 2.2
        assert clip.thumbnail_generated is True
        assert clip.storage_path is not None
        assert Path(clip.storage_path).exists()
        assert Path(clip.storage_path).read_bytes() == synthetic_clip_bytes

    assert FakeBlinkService.instances[-1].closed is True
    worker_ctx["redis"].enqueue_job.assert_awaited_once_with(ANALYZE_JOB_NAME, clip_id=str(clip_id))
    del camera_id


async def test_auto_analyze_false_skips_queueing_analysis(
    worker_ctx: dict[str, Any], tmp_path: Path, synthetic_clip_bytes: bytes
) -> None:
    async with worker_ctx["sessionmaker"]() as session:
        await set_storage_dir(session, str(tmp_path))
        _account, _camera, clip = await _make_account_camera_clip(session)
        clip_id = clip.id

    FakeBlinkService.next_bytes = synthetic_clip_bytes
    result = await download_clip(worker_ctx, str(clip_id), auto_analyze=False)
    assert result == "ok"

    async with worker_ctx["sessionmaker"]() as session:
        clip = await session.get(Clip, clip_id)
        assert clip is not None
        assert clip.downloaded_at is not None  # still downloaded

    worker_ctx["redis"].enqueue_job.assert_not_awaited()


async def test_auto_analyze_false_still_auto_archives_when_configured(
    worker_ctx: dict[str, Any], tmp_path: Path, synthetic_clip_bytes: bytes
) -> None:
    async with worker_ctx["sessionmaker"]() as session:
        await set_storage_dir(session, str(tmp_path))
        _account, _camera, clip = await _make_account_camera_clip(session)
        clip_id = clip.id
        await update_storage_integration_settings(
            session,
            StorageIntegrationSettingsUpdate(auto_archive_backend=StorageBackend.GOOGLE_DRIVE),
            get_settings().encryption_key,
        )

    FakeBlinkService.next_bytes = synthetic_clip_bytes
    result = await download_clip(worker_ctx, str(clip_id), auto_analyze=False)
    assert result == "ok"

    worker_ctx["redis"].enqueue_job.assert_awaited_once_with(
        ARCHIVE_CLIP_JOB_NAME, clip_id=str(clip_id), backend="google_drive"
    )


async def test_auto_archive_delay_defers_the_generic_job_instead(
    worker_ctx: dict[str, Any], tmp_path: Path, synthetic_clip_bytes: bytes
) -> None:
    async with worker_ctx["sessionmaker"]() as session:
        await set_storage_dir(session, str(tmp_path))
        _account, _camera, clip = await _make_account_camera_clip(session)
        clip_id = clip.id
        await update_storage_integration_settings(
            session,
            StorageIntegrationSettingsUpdate(
                auto_archive_backend=StorageBackend.GOOGLE_DRIVE, auto_archive_after_days=3
            ),
            get_settings().encryption_key,
        )

    FakeBlinkService.next_bytes = synthetic_clip_bytes
    result = await download_clip(worker_ctx, str(clip_id), auto_analyze=False)
    assert result == "ok"

    worker_ctx["redis"].enqueue_job.assert_awaited_once_with(
        AUTO_ARCHIVE_CLIP_JOB_NAME, clip_id=str(clip_id), _defer_by=timedelta(days=3)
    )


async def test_download_auth_error_marks_account_errored(worker_ctx: dict[str, Any]) -> None:
    async with worker_ctx["sessionmaker"]() as session:
        account, _camera, clip = await _make_account_camera_clip(session)
        account_id, clip_id = account.id, clip.id

    FakeBlinkService.next_error = BlinkAuthError("token expired")
    result = await download_clip(worker_ctx, str(clip_id))
    assert result == "auth_error"

    async with worker_ctx["sessionmaker"]() as session:
        account = await session.get(BlinkAccount, account_id)
        assert account is not None
        assert account.status == BlinkAccountStatus.ERROR
        assert account.last_error == "token expired"
    assert FakeBlinkService.instances[-1].closed is True


async def test_download_connection_error_propagates_for_arq_retry(
    worker_ctx: dict[str, Any],
) -> None:
    async with worker_ctx["sessionmaker"]() as session:
        _account, _camera, clip = await _make_account_camera_clip(session)
        clip_id = clip.id

    FakeBlinkService.next_error = BlinkError("temporary network blip")
    with pytest.raises(BlinkError):
        await download_clip(worker_ctx, str(clip_id))
    assert FakeBlinkService.instances[-1].closed is True


async def test_storage_error_propagates_for_arq_retry(
    worker_ctx: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    async with worker_ctx["sessionmaker"]() as session:
        _account, _camera, clip = await _make_account_camera_clip(session)
        clip_id = clip.id

    from app.storage.service import StorageError

    async def fail_write(*_args: object, **_kwargs: object) -> int:
        raise StorageError("disk full")

    monkeypatch.setattr("app.storage.service.LocalClipStorage.write", fail_write)
    FakeBlinkService.next_bytes = b"irrelevant"
    with pytest.raises(StorageError):
        await download_clip(worker_ctx, str(clip_id))


async def test_ffmpeg_binary_missing_does_not_fail_the_download(
    worker_ctx: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with worker_ctx["sessionmaker"]() as session:
        await set_storage_dir(session, str(tmp_path))
        _account, _camera, clip = await _make_account_camera_clip(session)
        clip_id = clip.id

    async def fake_exec(*_args: object, **_kwargs: object) -> None:
        raise FileNotFoundError("no such file: ffprobe")

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    FakeBlinkService.next_bytes = b"irrelevant"
    result = await download_clip(worker_ctx, str(clip_id))
    assert result == "ok"  # the file is still saved and marked downloaded

    async with worker_ctx["sessionmaker"]() as session:
        clip = await session.get(Clip, clip_id)
        assert clip is not None
        assert clip.downloaded_at is not None
        assert clip.duration_seconds is None


async def test_ffmpeg_failure_does_not_fail_the_download(
    worker_ctx: dict[str, Any], tmp_path: Path
) -> None:
    async with worker_ctx["sessionmaker"]() as session:
        await set_storage_dir(session, str(tmp_path))
        _account, _camera, clip = await _make_account_camera_clip(session)
        clip_id = clip.id

    FakeBlinkService.next_bytes = b"not a real video file at all"
    result = await download_clip(worker_ctx, str(clip_id))
    assert result == "ok"  # the file is still saved and marked downloaded

    async with worker_ctx["sessionmaker"]() as session:
        clip = await session.get(Clip, clip_id)
        assert clip is not None
        assert clip.downloaded_at is not None
        assert clip.duration_seconds is None
        assert clip.thumbnail_generated is False
