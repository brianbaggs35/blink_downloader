"""Sync Module service: arm/disarm, motion toggling, and local storage.

BlinkPyService is faked (patched at the name imported into
app.sync_module.service), matching test_livefeed_service.py's convention.
"""

# pytest calls autouse fixtures implicitly; pyright can't see that usage.
# pyright: reportUnusedFunction=false

import json
from datetime import UTC, datetime
from typing import Any, ClassVar

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.blink.models import BlinkAccount, BlinkAccountStatus, Camera
from app.blink.service import (
    BlinkAuthError,
    BlinkError,
    BlinkLocalStorageItem,
    BlinkLocalStorageManifest,
)
from app.config import get_settings
from app.security.crypto import SecretBox
from app.storage.service import get_clip_storage
from app.sync_module.models import (
    LocalItemStatus,
    LocalStorageStatus,
    SyncModule,
    SyncModuleLocalItem,
)
from app.sync_module.service import (
    MotionNotSupportedError,
    arm_sync_module,
    bulk_set_camera_motion_detection,
    delete_local_storage_item,
    download_local_storage_item,
    list_cameras_for_sync_module,
    list_local_items,
    list_sync_modules,
    refresh_local_storage_manifest,
    set_camera_motion_detection,
)
from tests.conftest import PlainSettings


class FakeBlinkService:
    next_manifest: ClassVar[BlinkLocalStorageManifest | None] = None
    next_download: ClassVar[bytes] = b"x" * 1024
    next_delete_result: ClassVar[bool] = True
    next_error: ClassVar[Exception | None] = None
    calls: ClassVar[list[str]] = []
    instances: ClassVar[list[FakeBlinkService]] = []

    def __init__(self, token_data: dict[str, Any]) -> None:
        self.token_data_in = dict(token_data)
        self.closed = False
        FakeBlinkService.instances.append(self)

    async def set_sync_module_arm(self, network_id: str, armed: bool) -> None:
        del network_id, armed
        FakeBlinkService.calls.append("arm")
        if FakeBlinkService.next_error:
            raise FakeBlinkService.next_error

    async def set_camera_motion_detection(
        self, network_id: str, camera_id: str, motion_bucket: str, enabled: bool
    ) -> None:
        del network_id, camera_id, motion_bucket, enabled
        FakeBlinkService.calls.append("motion")
        if FakeBlinkService.next_error:
            raise FakeBlinkService.next_error

    async def refresh_local_storage_manifest(self, network_id: str) -> BlinkLocalStorageManifest:
        del network_id
        FakeBlinkService.calls.append("refresh")
        if FakeBlinkService.next_error:
            raise FakeBlinkService.next_error
        assert FakeBlinkService.next_manifest is not None
        return FakeBlinkService.next_manifest

    async def prepare_local_storage_clip(
        self, network_id: str, sync_id: str, manifest_id: str, item_id: int
    ) -> None:
        del network_id, sync_id, manifest_id, item_id
        FakeBlinkService.calls.append("prepare")
        if FakeBlinkService.next_error:
            raise FakeBlinkService.next_error

    async def download_local_storage_clip(
        self, network_id: str, sync_id: str, manifest_id: str, item_id: int
    ) -> bytes:
        del network_id, sync_id, manifest_id, item_id
        FakeBlinkService.calls.append("download")
        if FakeBlinkService.next_error:
            raise FakeBlinkService.next_error
        return FakeBlinkService.next_download

    async def delete_local_storage_clip(
        self, network_id: str, sync_id: str, manifest_id: str, item_id: int
    ) -> bool:
        del network_id, sync_id, manifest_id, item_id
        FakeBlinkService.calls.append("delete")
        if FakeBlinkService.next_error:
            raise FakeBlinkService.next_error
        return FakeBlinkService.next_delete_result

    async def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_fake_service(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeBlinkService.instances = []
    FakeBlinkService.calls = []
    FakeBlinkService.next_error = None
    FakeBlinkService.next_manifest = None
    FakeBlinkService.next_download = b"x" * 1024
    FakeBlinkService.next_delete_result = True
    monkeypatch.setattr("app.sync_module.service.BlinkPyService", FakeBlinkService)


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


async def _make_camera(
    session: AsyncSession, account: BlinkAccount, *, name: str = "Front Door", mini: bool = False
) -> Camera:
    camera = Camera(
        blink_account_id=account.id,
        blink_camera_id=f"cam-{name}",
        blink_network_id="net-1",
        name=name,
        camera_type="catalina" if not mini else "owl",
        motion_action_type="mini" if mini else "default",
    )
    session.add(camera)
    await session.commit()
    await session.refresh(camera)
    return camera


async def _make_sync_module(
    session: AsyncSession, account: BlinkAccount, *, local_storage_manifest_id: str | None = "m-1"
) -> SyncModule:
    sync_module = SyncModule(
        blink_account_id=account.id,
        network_id="net-1",
        sync_id="sync-1",
        name="Home",
        is_physical_hub=True,
        online=True,
        local_storage_compatible=True,
        local_storage_enabled=True,
        local_storage_active=True,
        local_storage_manifest_id=local_storage_manifest_id,
    )
    session.add(sync_module)
    await session.commit()
    await session.refresh(sync_module)
    return sync_module


# --------------------------------------------------------------------- reads


async def test_list_sync_modules_returns_all(app_session: AsyncSession) -> None:
    account = await _make_account(app_session)
    await _make_sync_module(app_session, account)
    modules = await list_sync_modules(app_session)
    assert len(modules) == 1
    assert modules[0].name == "Home"


async def test_list_cameras_for_sync_module_filters_by_network(app_session: AsyncSession) -> None:
    account = await _make_account(app_session)
    sync_module = await _make_sync_module(app_session, account)
    camera = await _make_camera(app_session, account)
    other = Camera(
        blink_account_id=account.id,
        blink_camera_id="cam-other",
        blink_network_id="other-network",
        name="Other",
        camera_type="catalina",
    )
    app_session.add(other)
    await app_session.commit()

    cameras = await list_cameras_for_sync_module(app_session, sync_module)
    assert [c.id for c in cameras] == [camera.id]


async def test_list_local_items_orders_newest_first(app_session: AsyncSession) -> None:
    account = await _make_account(app_session)
    sync_module = await _make_sync_module(app_session, account)
    older = SyncModuleLocalItem(
        sync_module_id=sync_module.id,
        camera_name="Front Door",
        blink_item_id=1,
        recorded_at=datetime(2026, 7, 1, tzinfo=UTC),
        size_bytes=100,
    )
    newer = SyncModuleLocalItem(
        sync_module_id=sync_module.id,
        camera_name="Front Door",
        blink_item_id=2,
        recorded_at=datetime(2026, 7, 20, tzinfo=UTC),
        size_bytes=200,
    )
    app_session.add_all([older, newer])
    await app_session.commit()

    items = await list_local_items(app_session, sync_module)
    assert [item.blink_item_id for item in items] == [2, 1]


# -------------------------------------------------------------------- arming


async def test_arm_sync_module_calls_the_service_and_persists(app_session: AsyncSession) -> None:
    account = await _make_account(app_session)
    sync_module = await _make_sync_module(app_session, account)

    result = await arm_sync_module(app_session, get_settings(), sync_module, True)

    assert result.armed is True
    assert FakeBlinkService.calls == ["arm"]


async def test_arm_sync_module_maps_auth_errors(app_session: AsyncSession) -> None:
    account = await _make_account(app_session)
    sync_module = await _make_sync_module(app_session, account)
    FakeBlinkService.next_error = BlinkAuthError("token expired")

    with pytest.raises(BlinkAuthError):
        await arm_sync_module(app_session, get_settings(), sync_module, True)

    await app_session.refresh(account)
    assert account.status == BlinkAccountStatus.ERROR


async def test_arm_sync_module_raises_when_network_calls_disabled(
    app_session: AsyncSession,
) -> None:
    account = await _make_account(app_session)
    sync_module = await _make_sync_module(app_session, account)
    disabled_settings = PlainSettings(disable_blink_network_calls=True)

    with pytest.raises(BlinkError, match="disabled"):
        await arm_sync_module(app_session, disabled_settings, sync_module, True)

    assert FakeBlinkService.calls == []


# ---------------------------------------------------------- motion single


async def test_set_camera_motion_detection_calls_the_service_and_persists(
    app_session: AsyncSession,
) -> None:
    account = await _make_account(app_session)
    sync_module = await _make_sync_module(app_session, account)
    camera = await _make_camera(app_session, account)

    result = await set_camera_motion_detection(
        app_session, get_settings(), camera, sync_module, False
    )

    assert result.motion_enabled is False
    assert FakeBlinkService.calls == ["motion"]


async def test_set_camera_motion_detection_raises_for_a_mini(app_session: AsyncSession) -> None:
    account = await _make_account(app_session)
    sync_module = await _make_sync_module(app_session, account)
    mini = await _make_camera(app_session, account, name="Mini", mini=True)

    with pytest.raises(MotionNotSupportedError):
        await set_camera_motion_detection(app_session, get_settings(), mini, sync_module, True)

    assert FakeBlinkService.calls == []


async def test_set_camera_motion_detection_maps_auth_errors(app_session: AsyncSession) -> None:
    account = await _make_account(app_session)
    sync_module = await _make_sync_module(app_session, account)
    camera = await _make_camera(app_session, account)
    FakeBlinkService.next_error = BlinkAuthError("token expired")

    with pytest.raises(BlinkAuthError):
        await set_camera_motion_detection(app_session, get_settings(), camera, sync_module, True)

    await app_session.refresh(account)
    assert account.status == BlinkAccountStatus.ERROR


async def test_set_camera_motion_detection_raises_when_network_calls_disabled(
    app_session: AsyncSession,
) -> None:
    account = await _make_account(app_session)
    sync_module = await _make_sync_module(app_session, account)
    camera = await _make_camera(app_session, account)
    disabled_settings = PlainSettings(disable_blink_network_calls=True)

    with pytest.raises(BlinkError, match="disabled"):
        await set_camera_motion_detection(app_session, disabled_settings, camera, sync_module, True)

    assert FakeBlinkService.calls == []


# --------------------------------------------------------------- motion bulk


async def test_bulk_set_camera_motion_detection_applies_to_all_non_mini_cameras(
    app_session: AsyncSession,
) -> None:
    account = await _make_account(app_session)
    sync_module = await _make_sync_module(app_session, account)
    front = await _make_camera(app_session, account, name="Front Door")
    back = await _make_camera(app_session, account, name="Backyard")
    mini = await _make_camera(app_session, account, name="Mini", mini=True)

    succeeded, failed = await bulk_set_camera_motion_detection(
        app_session, get_settings(), sync_module, [front, back, mini], False
    )

    assert (succeeded, failed) == (2, 0)
    assert FakeBlinkService.calls == ["motion", "motion"]
    await app_session.refresh(front)
    await app_session.refresh(back)
    assert front.motion_enabled is False
    assert back.motion_enabled is False


async def test_bulk_set_camera_motion_detection_skips_only_minis(app_session: AsyncSession) -> None:
    account = await _make_account(app_session)
    sync_module = await _make_sync_module(app_session, account)
    mini = await _make_camera(app_session, account, name="Mini", mini=True)

    succeeded, failed = await bulk_set_camera_motion_detection(
        app_session, get_settings(), sync_module, [mini], True
    )

    assert (succeeded, failed) == (0, 0)
    assert FakeBlinkService.calls == []


async def test_bulk_set_camera_motion_detection_counts_non_auth_failures(
    app_session: AsyncSession,
) -> None:
    account = await _make_account(app_session)
    sync_module = await _make_sync_module(app_session, account)
    front = await _make_camera(app_session, account, name="Front Door")
    back = await _make_camera(app_session, account, name="Backyard")
    FakeBlinkService.next_error = BlinkError("camera offline")

    succeeded, failed = await bulk_set_camera_motion_detection(
        app_session, get_settings(), sync_module, [front, back], True
    )

    assert (succeeded, failed) == (0, 2)


async def test_bulk_set_camera_motion_detection_stops_retrying_after_an_auth_error(
    app_session: AsyncSession,
) -> None:
    account = await _make_account(app_session)
    sync_module = await _make_sync_module(app_session, account)
    front = await _make_camera(app_session, account, name="Front Door")
    back = await _make_camera(app_session, account, name="Backyard")
    third = await _make_camera(app_session, account, name="Side Yard")
    FakeBlinkService.next_error = BlinkAuthError("token expired")

    succeeded, failed = await bulk_set_camera_motion_detection(
        app_session, get_settings(), sync_module, [front, back, third], True
    )

    # Stops after the first attempt once the token itself is bad - the
    # remaining two are counted failed without ever being retried.
    assert (succeeded, failed) == (0, 3)
    assert FakeBlinkService.calls == ["motion"]
    await app_session.refresh(account)
    assert account.status == BlinkAccountStatus.ERROR


async def test_bulk_set_camera_motion_detection_raises_when_network_calls_disabled(
    app_session: AsyncSession,
) -> None:
    account = await _make_account(app_session)
    sync_module = await _make_sync_module(app_session, account)
    front = await _make_camera(app_session, account, name="Front Door")
    disabled_settings = PlainSettings(disable_blink_network_calls=True)

    with pytest.raises(BlinkError, match="disabled"):
        await bulk_set_camera_motion_detection(
            app_session, disabled_settings, sync_module, [front], True
        )


# --------------------------------------------------------- local storage refresh


async def test_refresh_local_storage_manifest_inserts_new_items(app_session: AsyncSession) -> None:
    account = await _make_account(app_session)
    sync_module = await _make_sync_module(app_session, account, local_storage_manifest_id=None)
    camera = await _make_camera(app_session, account, name="Front Door")
    recorded_at = datetime(2026, 7, 20, 10, 0, tzinfo=UTC)
    FakeBlinkService.next_manifest = BlinkLocalStorageManifest(
        manifest_id="m-2",
        items=[
            BlinkLocalStorageItem(
                item_id=1, camera_name="Front Door", recorded_at=recorded_at, size_bytes=1024
            )
        ],
    )

    await refresh_local_storage_manifest(app_session, get_settings(), sync_module)

    await app_session.refresh(sync_module)
    assert sync_module.local_storage_status == LocalStorageStatus.IDLE
    assert sync_module.local_storage_manifest_id == "m-2"
    items = await list_local_items(app_session, sync_module)
    assert len(items) == 1
    assert items[0].camera_id == camera.id
    assert items[0].blink_item_id == 1
    assert items[0].present_on_device is True


async def test_refresh_local_storage_manifest_keeps_unmatched_camera_name(
    app_session: AsyncSession,
) -> None:
    account = await _make_account(app_session)
    sync_module = await _make_sync_module(app_session, account, local_storage_manifest_id=None)
    FakeBlinkService.next_manifest = BlinkLocalStorageManifest(
        manifest_id="m-2",
        items=[
            BlinkLocalStorageItem(
                item_id=1,
                camera_name="Unknown Camera",
                recorded_at=datetime.now(UTC),
                size_bytes=1024,
            )
        ],
    )

    await refresh_local_storage_manifest(app_session, get_settings(), sync_module)

    items = await list_local_items(app_session, sync_module)
    assert items[0].camera_id is None
    assert items[0].camera_name == "Unknown Camera"


async def test_refresh_local_storage_manifest_updates_an_existing_item(
    app_session: AsyncSession,
) -> None:
    account = await _make_account(app_session)
    sync_module = await _make_sync_module(app_session, account, local_storage_manifest_id="m-1")
    recorded_at = datetime(2026, 7, 20, 10, 0, tzinfo=UTC)
    existing = SyncModuleLocalItem(
        sync_module_id=sync_module.id,
        camera_name="Front Door",
        blink_item_id=1,
        recorded_at=recorded_at,
        size_bytes=100,
    )
    app_session.add(existing)
    await app_session.commit()
    FakeBlinkService.next_manifest = BlinkLocalStorageManifest(
        manifest_id="m-2",
        items=[
            BlinkLocalStorageItem(
                item_id=1, camera_name="Front Door", recorded_at=recorded_at, size_bytes=999
            )
        ],
    )

    await refresh_local_storage_manifest(app_session, get_settings(), sync_module)

    items = await list_local_items(app_session, sync_module)
    assert len(items) == 1
    assert items[0].id == existing.id
    assert items[0].size_bytes == 999


async def test_refresh_local_storage_manifest_drops_a_never_downloaded_item_no_longer_listed(
    app_session: AsyncSession,
) -> None:
    account = await _make_account(app_session)
    sync_module = await _make_sync_module(app_session, account, local_storage_manifest_id="m-1")
    stale = SyncModuleLocalItem(
        sync_module_id=sync_module.id,
        camera_name="Front Door",
        blink_item_id=99,
        recorded_at=datetime.now(UTC),
        size_bytes=100,
        status=LocalItemStatus.AVAILABLE,
    )
    app_session.add(stale)
    await app_session.commit()
    FakeBlinkService.next_manifest = BlinkLocalStorageManifest(manifest_id="m-2", items=[])

    await refresh_local_storage_manifest(app_session, get_settings(), sync_module)

    items = await list_local_items(app_session, sync_module)
    assert items == []


async def test_refresh_local_storage_manifest_keeps_a_downloaded_item_as_absent(
    app_session: AsyncSession,
) -> None:
    account = await _make_account(app_session)
    sync_module = await _make_sync_module(app_session, account, local_storage_manifest_id="m-1")
    downloaded = SyncModuleLocalItem(
        sync_module_id=sync_module.id,
        camera_name="Front Door",
        blink_item_id=99,
        recorded_at=datetime.now(UTC),
        size_bytes=100,
        status=LocalItemStatus.DOWNLOADED,
        storage_path="/data/sync-module/x.mp4",
    )
    app_session.add(downloaded)
    await app_session.commit()
    FakeBlinkService.next_manifest = BlinkLocalStorageManifest(manifest_id="m-2", items=[])

    await refresh_local_storage_manifest(app_session, get_settings(), sync_module)

    items = await list_local_items(app_session, sync_module)
    assert len(items) == 1
    assert items[0].present_on_device is False
    assert items[0].storage_path == "/data/sync-module/x.mp4"


async def test_refresh_local_storage_manifest_maps_auth_errors(app_session: AsyncSession) -> None:
    account = await _make_account(app_session)
    sync_module = await _make_sync_module(app_session, account)
    FakeBlinkService.next_error = BlinkAuthError("token expired")

    with pytest.raises(BlinkAuthError):
        await refresh_local_storage_manifest(app_session, get_settings(), sync_module)

    await app_session.refresh(account)
    assert account.status == BlinkAccountStatus.ERROR


async def test_refresh_local_storage_manifest_raises_when_network_calls_disabled(
    app_session: AsyncSession,
) -> None:
    account = await _make_account(app_session)
    sync_module = await _make_sync_module(app_session, account)
    disabled_settings = PlainSettings(disable_blink_network_calls=True)

    with pytest.raises(BlinkError, match="disabled"):
        await refresh_local_storage_manifest(app_session, disabled_settings, sync_module)

    await app_session.refresh(sync_module)
    assert sync_module.local_storage_status == LocalStorageStatus.REFRESHING


# ------------------------------------------------------- local storage download


async def test_download_local_storage_item_writes_the_file(
    app_session: AsyncSession, tmp_path: Any
) -> None:
    account = await _make_account(app_session)
    sync_module = await _make_sync_module(app_session, account)
    item = SyncModuleLocalItem(
        sync_module_id=sync_module.id,
        camera_name="Front Door",
        blink_item_id=1,
        recorded_at=datetime.now(UTC),
        size_bytes=1024,
    )
    app_session.add(item)
    await app_session.commit()
    storage = get_clip_storage(tmp_path)

    await download_local_storage_item(app_session, get_settings(), storage, item, sync_module)

    assert FakeBlinkService.calls == ["prepare", "download"]
    await app_session.refresh(item)
    assert item.status == LocalItemStatus.DOWNLOADED
    assert item.storage_path is not None
    assert item.downloaded_at is not None


async def test_download_local_storage_item_rejects_a_size_mismatch(
    app_session: AsyncSession, tmp_path: Any
) -> None:
    # A truncated/garbage download (network blip, sync module still
    # uploading, etc.) must not be accepted as a valid clip just because
    # bytes came back - nothing else in this path checks the byte count
    # against what the manifest itself already told us to expect.
    account = await _make_account(app_session)
    sync_module = await _make_sync_module(app_session, account)
    item = SyncModuleLocalItem(
        sync_module_id=sync_module.id,
        camera_name="Front Door",
        blink_item_id=1,
        recorded_at=datetime.now(UTC),
        size_bytes=2048,
    )
    app_session.add(item)
    await app_session.commit()
    storage = get_clip_storage(tmp_path)
    FakeBlinkService.next_download = b"truncated"

    with pytest.raises(BlinkError, match="truncated"):
        await download_local_storage_item(app_session, get_settings(), storage, item, sync_module)

    await app_session.refresh(item)
    assert item.storage_path is None
    assert item.status != LocalItemStatus.DOWNLOADED


async def test_download_local_storage_item_raises_without_a_manifest(
    app_session: AsyncSession, tmp_path: Any
) -> None:
    account = await _make_account(app_session)
    sync_module = await _make_sync_module(app_session, account, local_storage_manifest_id=None)
    item = SyncModuleLocalItem(
        sync_module_id=sync_module.id,
        camera_name="Front Door",
        blink_item_id=1,
        recorded_at=datetime.now(UTC),
        size_bytes=1024,
    )
    app_session.add(item)
    await app_session.commit()
    storage = get_clip_storage(tmp_path)

    with pytest.raises(BlinkError, match="refresh first"):
        await download_local_storage_item(app_session, get_settings(), storage, item, sync_module)

    assert FakeBlinkService.calls == []


async def test_download_local_storage_item_maps_auth_errors(
    app_session: AsyncSession, tmp_path: Any
) -> None:
    account = await _make_account(app_session)
    sync_module = await _make_sync_module(app_session, account)
    item = SyncModuleLocalItem(
        sync_module_id=sync_module.id,
        camera_name="Front Door",
        blink_item_id=1,
        recorded_at=datetime.now(UTC),
        size_bytes=1024,
    )
    app_session.add(item)
    await app_session.commit()
    storage = get_clip_storage(tmp_path)
    FakeBlinkService.next_error = BlinkAuthError("token expired")

    with pytest.raises(BlinkAuthError):
        await download_local_storage_item(app_session, get_settings(), storage, item, sync_module)

    await app_session.refresh(account)
    assert account.status == BlinkAccountStatus.ERROR


async def test_download_local_storage_item_raises_when_network_calls_disabled(
    app_session: AsyncSession, tmp_path: Any
) -> None:
    account = await _make_account(app_session)
    sync_module = await _make_sync_module(app_session, account)
    item = SyncModuleLocalItem(
        sync_module_id=sync_module.id,
        camera_name="Front Door",
        blink_item_id=1,
        recorded_at=datetime.now(UTC),
        size_bytes=1024,
    )
    app_session.add(item)
    await app_session.commit()
    storage = get_clip_storage(tmp_path)
    disabled_settings = PlainSettings(disable_blink_network_calls=True)

    with pytest.raises(BlinkError, match="disabled"):
        await download_local_storage_item(
            app_session, disabled_settings, storage, item, sync_module
        )

    assert FakeBlinkService.calls == []


# --------------------------------------------------------- local storage delete


async def test_delete_local_storage_item_removes_the_row(app_session: AsyncSession) -> None:
    account = await _make_account(app_session)
    sync_module = await _make_sync_module(app_session, account)
    item = SyncModuleLocalItem(
        sync_module_id=sync_module.id,
        camera_name="Front Door",
        blink_item_id=1,
        recorded_at=datetime.now(UTC),
        size_bytes=1024,
    )
    app_session.add(item)
    await app_session.commit()
    item_id = item.id

    await delete_local_storage_item(app_session, get_settings(), item, sync_module)

    assert FakeBlinkService.calls == ["delete"]
    remaining = (
        await app_session.execute(
            select(SyncModuleLocalItem).where(SyncModuleLocalItem.id == item_id)
        )
    ).scalar_one_or_none()
    assert remaining is None


async def test_delete_local_storage_item_raises_when_the_device_reports_failure(
    app_session: AsyncSession,
) -> None:
    account = await _make_account(app_session)
    sync_module = await _make_sync_module(app_session, account)
    item = SyncModuleLocalItem(
        sync_module_id=sync_module.id,
        camera_name="Front Door",
        blink_item_id=1,
        recorded_at=datetime.now(UTC),
        size_bytes=1024,
    )
    app_session.add(item)
    await app_session.commit()
    FakeBlinkService.next_delete_result = False

    with pytest.raises(BlinkError, match="Could not delete"):
        await delete_local_storage_item(app_session, get_settings(), item, sync_module)


async def test_delete_local_storage_item_raises_without_a_manifest(
    app_session: AsyncSession,
) -> None:
    account = await _make_account(app_session)
    sync_module = await _make_sync_module(app_session, account, local_storage_manifest_id=None)
    item = SyncModuleLocalItem(
        sync_module_id=sync_module.id,
        camera_name="Front Door",
        blink_item_id=1,
        recorded_at=datetime.now(UTC),
        size_bytes=1024,
    )
    app_session.add(item)
    await app_session.commit()

    with pytest.raises(BlinkError, match="refresh first"):
        await delete_local_storage_item(app_session, get_settings(), item, sync_module)

    assert FakeBlinkService.calls == []


async def test_delete_local_storage_item_maps_auth_errors(app_session: AsyncSession) -> None:
    account = await _make_account(app_session)
    sync_module = await _make_sync_module(app_session, account)
    item = SyncModuleLocalItem(
        sync_module_id=sync_module.id,
        camera_name="Front Door",
        blink_item_id=1,
        recorded_at=datetime.now(UTC),
        size_bytes=1024,
    )
    app_session.add(item)
    await app_session.commit()
    FakeBlinkService.next_error = BlinkAuthError("token expired")

    with pytest.raises(BlinkAuthError):
        await delete_local_storage_item(app_session, get_settings(), item, sync_module)

    await app_session.refresh(account)
    assert account.status == BlinkAccountStatus.ERROR


async def test_delete_local_storage_item_raises_when_network_calls_disabled(
    app_session: AsyncSession,
) -> None:
    account = await _make_account(app_session)
    sync_module = await _make_sync_module(app_session, account)
    item = SyncModuleLocalItem(
        sync_module_id=sync_module.id,
        camera_name="Front Door",
        blink_item_id=1,
        recorded_at=datetime.now(UTC),
        size_bytes=1024,
    )
    app_session.add(item)
    await app_session.commit()
    disabled_settings = PlainSettings(disable_blink_network_calls=True)

    with pytest.raises(BlinkError, match="disabled"):
        await delete_local_storage_item(app_session, disabled_settings, item, sync_module)

    assert FakeBlinkService.calls == []
