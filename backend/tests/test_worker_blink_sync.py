"""sync_blink_account: camera/clip upserts, download fan-out, error handling.

BlinkPyService is faked (patched at the name imported into
app.worker.tasks.blink_sync) — this tests our sync orchestration against a
real database, not blinkpy itself. Each test configures FakeBlinkService's
class-level "next instance" fields *before* calling the task, since the task
constructs its own instance internally.
"""

# pytest calls autouse fixtures implicitly; pyright can't see that usage.
# pyright: reportUnusedFunction=false

import json
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.blink.models import BlinkAccount, BlinkAccountStatus, Camera, Clip
from app.blink.service import (
    BlinkAuthError,
    BlinkCameraInfo,
    BlinkError,
    BlinkMediaItem,
    BlinkSyncModuleInfo,
)
from app.config import get_settings
from app.security.crypto import SecretBox
from app.sync_module.models import SyncModule
from app.worker.tasks.blink_sync import SYNC_JOB_NAME, sync_blink_account
from app.worker.tasks.download import DOWNLOAD_JOB_NAME


class FakeBlinkService:
    next_cameras: ClassVar[list[BlinkCameraInfo]] = []
    next_sync_modules: ClassVar[list[BlinkSyncModuleInfo]] = []
    next_media: ClassVar[list[BlinkMediaItem]] = []
    next_get_cameras_error: ClassVar[Exception | None] = None
    next_list_media_error: ClassVar[Exception | None] = None
    instances: ClassVar[list[FakeBlinkService]] = []

    def __init__(self, token_data: dict[str, Any]) -> None:
        self.token_data_in = dict(token_data)
        self.cameras_result = FakeBlinkService.next_cameras
        self.sync_modules_result = FakeBlinkService.next_sync_modules
        self.media_result = FakeBlinkService.next_media
        self.get_cameras_error = FakeBlinkService.next_get_cameras_error
        self.list_media_error = FakeBlinkService.next_list_media_error
        self.since_received: datetime | None = None
        self.closed = False
        FakeBlinkService.instances.append(self)

    async def get_cameras(self) -> list[BlinkCameraInfo]:
        if self.get_cameras_error:
            raise self.get_cameras_error
        return self.cameras_result

    async def get_sync_modules(self) -> list[BlinkSyncModuleInfo]:
        return self.sync_modules_result

    async def list_media(self, since: datetime | None = None) -> list[BlinkMediaItem]:
        self.since_received = since
        if self.list_media_error:
            raise self.list_media_error
        return self.media_result

    @property
    def token_data(self) -> dict[str, Any]:
        return {**self.token_data_in, "token": "rotated-token"}

    async def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_fake_service(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeBlinkService.instances = []
    FakeBlinkService.next_cameras = []
    FakeBlinkService.next_sync_modules = []
    FakeBlinkService.next_media = []
    FakeBlinkService.next_get_cameras_error = None
    FakeBlinkService.next_list_media_error = None
    monkeypatch.setattr("app.worker.tasks.blink_sync.BlinkPyService", FakeBlinkService)


async def _make_account(session: AsyncSession) -> BlinkAccount:
    box = SecretBox(get_settings().encryption_key)
    account = BlinkAccount(
        encrypted_username=box.encrypt("brian@example.com"),
        encrypted_password=box.encrypt("hunter2"),
        encrypted_token_data=box.encrypt(json.dumps({"refresh_token": "r"})),
    )
    session.add(account)
    await session.commit()
    await session.refresh(account)
    return account


def _camera_info(name: str = "Front Door", **overrides: Any) -> BlinkCameraInfo:
    defaults: dict[str, Any] = {
        "camera_id": "cam-1",
        "network_id": "net-1",
        "name": name,
        "camera_type": "catalina",
        "battery": "ok",
        "thumbnail_path": "/media/thumb.jpg",
        "motion_enabled": True,
        "motion_action_type": "default",
    }
    return BlinkCameraInfo(**{**defaults, **overrides})


def _sync_module_info(**overrides: Any) -> BlinkSyncModuleInfo:
    defaults: dict[str, Any] = {
        "network_id": "net-1",
        "sync_id": "sync-1",
        "name": "Home",
        "serial": "SN123",
        "firmware_version": "2.1.0",
        "is_physical_hub": True,
        "armed": True,
        "online": True,
        "local_storage_compatible": True,
        "local_storage_enabled": True,
        "local_storage_active": True,
    }
    return BlinkSyncModuleInfo(**{**defaults, **overrides})


def _media_item(camera_name: str = "Front Door", **overrides: Any) -> BlinkMediaItem:
    defaults: dict[str, Any] = {
        "media_id": "/media/clip1.mp4",
        "camera_name": camera_name,
        "created_at": datetime(2026, 7, 20, tzinfo=UTC),
        "deleted": False,
        "raw": {"some": "metadata"},
    }
    return BlinkMediaItem(**{**defaults, **overrides})


async def test_no_account_linked_is_a_clean_noop(worker_ctx: dict[str, Any]) -> None:
    result = await sync_blink_account(worker_ctx)
    assert result == "no_account_linked"
    worker_ctx["redis"].enqueue_job.assert_awaited_once_with(
        SYNC_JOB_NAME, _defer_by=get_settings().blink_sync_interval_seconds
    )


async def test_full_sync_upserts_camera_and_new_clip(worker_ctx: dict[str, Any]) -> None:
    async with worker_ctx["sessionmaker"]() as session:
        account = await _make_account(session)
        account_id = account.id

    FakeBlinkService.next_cameras = [_camera_info()]
    FakeBlinkService.next_sync_modules = [_sync_module_info()]
    FakeBlinkService.next_media = [_media_item()]

    result = await sync_blink_account(worker_ctx)
    assert result == "ok"

    async with worker_ctx["sessionmaker"]() as session:
        account = await session.get(BlinkAccount, account_id)
        assert account is not None
        assert account.status == BlinkAccountStatus.ACTIVE
        assert account.last_error is None
        assert account.last_sync is not None

        camera = (await session.execute(select(Camera))).scalar_one()
        assert camera.name == "Front Door"
        assert camera.blink_camera_id == "cam-1"
        assert camera.motion_enabled is True
        assert camera.motion_action_type == "default"

        sync_module = (await session.execute(select(SyncModule))).scalar_one()
        assert sync_module.network_id == "net-1"
        assert sync_module.name == "Home"
        assert sync_module.armed is True
        assert sync_module.local_storage_active is True

        clip = (await session.execute(select(Clip))).scalar_one()
        assert clip.blink_clip_id == "/media/clip1.mp4"
        assert clip.camera_id == camera.id

    worker_ctx["redis"].enqueue_job.assert_any_call(
        DOWNLOAD_JOB_NAME, clip_id=str(clip.id), auto_analyze=True
    )


async def test_caps_auto_analysis_to_the_most_recent_clips_in_a_large_batch(
    worker_ctx: dict[str, Any],
) -> None:
    """A first connection or a reconnect after an outage can turn up many new
    clips in one sync — only the most recent blink_auto_analyze_limit should
    auto-queue for AI analysis; the rest still download (auto_analyze=False)."""
    async with worker_ctx["sessionmaker"]() as session:
        await _make_account(session)

    limit = get_settings().blink_auto_analyze_limit
    total = limit + 2
    FakeBlinkService.next_cameras = [_camera_info()]
    FakeBlinkService.next_media = [
        _media_item(
            media_id=f"/media/clip{i}.mp4",
            created_at=datetime(2026, 7, 20, tzinfo=UTC) + timedelta(minutes=i),
        )
        for i in range(total)
    ]

    result = await sync_blink_account(worker_ctx)
    assert result == "ok"

    async with worker_ctx["sessionmaker"]() as session:
        clips = (await session.execute(select(Clip))).scalars().all()
        assert len(clips) == total
        newest_first = sorted(clips, key=lambda c: c.recorded_at, reverse=True)

    calls = {
        call.kwargs["clip_id"]: call.kwargs["auto_analyze"]
        for call in worker_ctx["redis"].enqueue_job.await_args_list
        if call.args and call.args[0] == DOWNLOAD_JOB_NAME
    }
    assert len(calls) == total
    for clip in newest_first[:limit]:
        assert calls[str(clip.id)] is True
    for clip in newest_first[limit:]:
        assert calls[str(clip.id)] is False


async def test_token_data_is_rotated_and_reencrypted(worker_ctx: dict[str, Any]) -> None:
    async with worker_ctx["sessionmaker"]() as session:
        account = await _make_account(session)
        account_id = account.id

    await sync_blink_account(worker_ctx)

    box = SecretBox(get_settings().encryption_key)
    async with worker_ctx["sessionmaker"]() as session:
        account = await session.get(BlinkAccount, account_id)
        assert account is not None
        stored = json.loads(box.decrypt(account.encrypted_token_data))
        assert stored["token"] == "rotated-token"


async def test_second_sync_updates_existing_camera_and_skips_duplicate_clip(
    worker_ctx: dict[str, Any],
) -> None:
    async with worker_ctx["sessionmaker"]() as session:
        await _make_account(session)

    FakeBlinkService.next_cameras = [_camera_info(battery="ok")]
    FakeBlinkService.next_sync_modules = [_sync_module_info(armed=True)]
    FakeBlinkService.next_media = [_media_item()]
    await sync_blink_account(worker_ctx)

    FakeBlinkService.next_cameras = [_camera_info(battery="low")]
    FakeBlinkService.next_sync_modules = [_sync_module_info(armed=False)]
    FakeBlinkService.next_media = [_media_item()]  # same clip again
    await sync_blink_account(worker_ctx)

    async with worker_ctx["sessionmaker"]() as session:
        cameras = (await session.execute(select(Camera))).scalars().all()
        assert len(cameras) == 1
        assert cameras[0].battery == "low"  # updated, not duplicated

        sync_modules = (await session.execute(select(SyncModule))).scalars().all()
        assert len(sync_modules) == 1
        assert sync_modules[0].armed is False  # updated, not duplicated

        clips = (await session.execute(select(Clip))).scalars().all()
        assert len(clips) == 1  # not duplicated


async def test_skips_media_for_unrecognized_camera(worker_ctx: dict[str, Any]) -> None:
    async with worker_ctx["sessionmaker"]() as session:
        await _make_account(session)

    FakeBlinkService.next_cameras = [_camera_info(name="Front Door")]
    FakeBlinkService.next_media = [_media_item(camera_name="Some Other Camera")]
    result = await sync_blink_account(worker_ctx)
    assert result == "ok"

    async with worker_ctx["sessionmaker"]() as session:
        clips = (await session.execute(select(Clip))).scalars().all()
        assert clips == []


async def test_skips_deleted_media_items(worker_ctx: dict[str, Any]) -> None:
    async with worker_ctx["sessionmaker"]() as session:
        await _make_account(session)

    FakeBlinkService.next_cameras = [_camera_info()]
    FakeBlinkService.next_media = [_media_item(deleted=True)]
    await sync_blink_account(worker_ctx)

    async with worker_ctx["sessionmaker"]() as session:
        clips = (await session.execute(select(Clip))).scalars().all()
        assert clips == []


async def test_first_sync_uses_initial_sync_window(worker_ctx: dict[str, Any]) -> None:
    async with worker_ctx["sessionmaker"]() as session:
        await _make_account(session)

    await sync_blink_account(worker_ctx)
    svc = FakeBlinkService.instances[-1]
    expected_floor = datetime.now(UTC) - timedelta(
        days=get_settings().blink_initial_sync_days, minutes=1
    )
    assert svc.since_received is not None
    assert svc.since_received > expected_floor


async def test_later_sync_uses_last_sync_as_since(worker_ctx: dict[str, Any]) -> None:
    fixed_last_sync = datetime(2026, 1, 1, tzinfo=UTC)
    async with worker_ctx["sessionmaker"]() as session:
        account = await _make_account(session)
        account.last_sync = fixed_last_sync
        await session.commit()

    await sync_blink_account(worker_ctx)
    assert FakeBlinkService.instances[-1].since_received == fixed_last_sync


async def test_auth_error_marks_account_errored_and_still_reschedules(
    worker_ctx: dict[str, Any],
) -> None:
    async with worker_ctx["sessionmaker"]() as session:
        account = await _make_account(session)
        account_id = account.id

    FakeBlinkService.next_get_cameras_error = BlinkAuthError("token expired")
    result = await sync_blink_account(worker_ctx)
    assert result == "auth_error"

    async with worker_ctx["sessionmaker"]() as session:
        account = await session.get(BlinkAccount, account_id)
        assert account is not None
        assert account.status == BlinkAccountStatus.ERROR
        assert account.last_error == "token expired"
    assert FakeBlinkService.instances[-1].closed is True
    worker_ctx["redis"].enqueue_job.assert_awaited_once()


async def test_generic_blink_error_marks_account_errored(worker_ctx: dict[str, Any]) -> None:
    async with worker_ctx["sessionmaker"]() as session:
        account = await _make_account(session)
        account_id = account.id

    FakeBlinkService.next_list_media_error = BlinkError("temporary blip")
    result = await sync_blink_account(worker_ctx)
    assert result == "error"

    async with worker_ctx["sessionmaker"]() as session:
        account = await session.get(BlinkAccount, account_id)
        assert account is not None
        assert account.status == BlinkAccountStatus.ERROR


async def test_service_is_closed_on_success_too(worker_ctx: dict[str, Any]) -> None:
    async with worker_ctx["sessionmaker"]() as session:
        await _make_account(session)

    await sync_blink_account(worker_ctx)
    assert FakeBlinkService.instances[-1].closed is True


async def test_unexpected_exception_still_reschedules(
    worker_ctx: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    async with worker_ctx["sessionmaker"]() as session:
        await _make_account(session)

    def boom(_token_data: dict[str, Any]) -> FakeBlinkService:
        msg = "unexpected programming error"
        raise RuntimeError(msg)

    monkeypatch.setattr("app.worker.tasks.blink_sync.BlinkPyService", boom)
    with pytest.raises(RuntimeError):
        await sync_blink_account(worker_ctx)
    worker_ctx["redis"].enqueue_job.assert_awaited_once_with(
        SYNC_JOB_NAME, _defer_by=get_settings().blink_sync_interval_seconds
    )
