"""refresh_sync_module_local_storage_job/download_sync_module_local_item_job/
delete_sync_module_local_item_job: the worker entrypoints that resolve a
sync module or local item, then delegate to app.sync_module.service.

BlinkPyService is faked at the name imported into app.sync_module.service -
same convention as test_sync_module_service.py.
"""

# pytest calls autouse fixtures implicitly; pyright can't see that usage.
# pyright: reportUnusedFunction=false

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

import pytest
from sqlalchemy import select

from app.blink.models import BlinkAccount
from app.blink.service import (
    BlinkAuthError,
    BlinkError,
    BlinkLocalStorageItem,
    BlinkLocalStorageManifest,
)
from app.config import get_settings
from app.security.crypto import SecretBox
from app.settings.service import set_storage_dir
from app.sync_module.models import (
    LocalItemStatus,
    LocalStorageStatus,
    SyncModule,
    SyncModuleLocalItem,
)
from app.worker.tasks.sync_module import (
    PERIODIC_LOCAL_STORAGE_REFRESH_INTERVAL_SECONDS,
    PERIODIC_LOCAL_STORAGE_REFRESH_JOB_NAME,
    REFRESH_LOCAL_STORAGE_JOB_NAME,
    delete_sync_module_local_item_job,
    download_sync_module_local_item_job,
    periodic_local_storage_refresh_job,
    refresh_sync_module_local_storage_job,
)


class FakeBlinkService:
    next_manifest: ClassVar[Any] = None
    next_download: ClassVar[bytes] = b"x" * 1024
    next_delete_result: ClassVar[bool] = True
    next_error: ClassVar[Exception | None] = None
    instances: ClassVar[list[FakeBlinkService]] = []

    def __init__(self, token_data: dict[str, Any]) -> None:
        self.token_data_in = dict(token_data)
        self.closed = False
        FakeBlinkService.instances.append(self)

    async def refresh_local_storage_manifest(self, network_id: str) -> Any:
        del network_id
        if FakeBlinkService.next_error:
            raise FakeBlinkService.next_error
        return FakeBlinkService.next_manifest

    async def prepare_local_storage_clip(
        self, network_id: str, sync_id: str, manifest_id: str, item_id: int
    ) -> None:
        del network_id, sync_id, manifest_id, item_id
        if FakeBlinkService.next_error:
            raise FakeBlinkService.next_error

    async def download_local_storage_clip(
        self, network_id: str, sync_id: str, manifest_id: str, item_id: int
    ) -> bytes:
        del network_id, sync_id, manifest_id, item_id
        if FakeBlinkService.next_error:
            raise FakeBlinkService.next_error
        return FakeBlinkService.next_download

    async def delete_local_storage_clip(
        self, network_id: str, sync_id: str, manifest_id: str, item_id: int
    ) -> bool:
        del network_id, sync_id, manifest_id, item_id
        if FakeBlinkService.next_error:
            raise FakeBlinkService.next_error
        return FakeBlinkService.next_delete_result

    async def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_fake_service(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeBlinkService.instances = []
    FakeBlinkService.next_error = None
    FakeBlinkService.next_manifest = None
    FakeBlinkService.next_download = b"x" * 1024
    FakeBlinkService.next_delete_result = True
    monkeypatch.setattr("app.sync_module.service.BlinkPyService", FakeBlinkService)


async def _make_account(ctx: dict[str, Any]) -> BlinkAccount:
    async with ctx["sessionmaker"]() as session:
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


async def _make_sync_module(ctx: dict[str, Any], account: BlinkAccount) -> SyncModule:
    async with ctx["sessionmaker"]() as session:
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
            local_storage_manifest_id="m-1",
        )
        session.add(sync_module)
        await session.commit()
        await session.refresh(sync_module)
        return sync_module


async def _make_local_item(ctx: dict[str, Any], sync_module: SyncModule) -> SyncModuleLocalItem:
    async with ctx["sessionmaker"]() as session:
        item = SyncModuleLocalItem(
            sync_module_id=sync_module.id,
            camera_name="Front Door",
            blink_item_id=1,
            recorded_at=datetime.now(UTC),
            size_bytes=1024,
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)
        return item


# ------------------------------------------------------------------ refresh


async def test_refresh_job_returns_sync_module_not_found(worker_ctx: dict[str, Any]) -> None:
    result = await refresh_sync_module_local_storage_job(worker_ctx, str(uuid.uuid4()))
    assert result == "sync_module_not_found"


async def test_refresh_job_succeeds(worker_ctx: dict[str, Any]) -> None:
    account = await _make_account(worker_ctx)
    sync_module = await _make_sync_module(worker_ctx, account)
    recorded_at = datetime(2026, 7, 20, tzinfo=UTC)
    FakeBlinkService.next_manifest = BlinkLocalStorageManifest(
        manifest_id="m-2",
        items=[
            BlinkLocalStorageItem(
                item_id=1, camera_name="Front Door", recorded_at=recorded_at, size_bytes=2048
            )
        ],
    )

    result = await refresh_sync_module_local_storage_job(worker_ctx, str(sync_module.id))
    assert result == "ok"

    async with worker_ctx["sessionmaker"]() as session:
        refreshed = await session.get(SyncModule, sync_module.id)
        assert refreshed is not None
        assert refreshed.local_storage_status == LocalStorageStatus.IDLE
        items = (await session.execute(select(SyncModuleLocalItem))).scalars().all()
        assert len(items) == 1
        assert items[0].size_bytes == 2048


async def test_refresh_job_reports_failure_and_sets_error_status(
    worker_ctx: dict[str, Any],
) -> None:
    account = await _make_account(worker_ctx)
    sync_module = await _make_sync_module(worker_ctx, account)
    FakeBlinkService.next_error = BlinkError("device busy")

    result = await refresh_sync_module_local_storage_job(worker_ctx, str(sync_module.id))
    assert result == "failed: device busy"

    async with worker_ctx["sessionmaker"]() as session:
        refreshed = await session.get(SyncModule, sync_module.id)
        assert refreshed is not None
        assert refreshed.local_storage_status == LocalStorageStatus.ERROR
        assert refreshed.local_storage_last_error == "device busy"


async def test_refresh_job_maps_auth_errors_too(worker_ctx: dict[str, Any]) -> None:
    account = await _make_account(worker_ctx)
    sync_module = await _make_sync_module(worker_ctx, account)
    FakeBlinkService.next_error = BlinkAuthError("token expired")

    result = await refresh_sync_module_local_storage_job(worker_ctx, str(sync_module.id))
    assert result == "failed: token expired"

    async with worker_ctx["sessionmaker"]() as session:
        refreshed_account = await session.get(BlinkAccount, account.id)
        assert refreshed_account is not None
        assert refreshed_account.status.value == "error"


# ----------------------------------------------------------------- download


async def test_download_job_returns_item_not_found(worker_ctx: dict[str, Any]) -> None:
    result = await download_sync_module_local_item_job(worker_ctx, str(uuid.uuid4()))
    assert result == "item_not_found"


async def test_download_job_succeeds(worker_ctx: dict[str, Any], tmp_path: Path) -> None:
    async with worker_ctx["sessionmaker"]() as session:
        await set_storage_dir(session, str(tmp_path))
    account = await _make_account(worker_ctx)
    sync_module = await _make_sync_module(worker_ctx, account)
    item = await _make_local_item(worker_ctx, sync_module)

    result = await download_sync_module_local_item_job(worker_ctx, str(item.id))
    assert result == "ok"

    async with worker_ctx["sessionmaker"]() as session:
        refreshed = await session.get(SyncModuleLocalItem, item.id)
        assert refreshed is not None
        assert refreshed.status == LocalItemStatus.DOWNLOADED
        assert refreshed.storage_path is not None


async def test_download_job_reports_failure_and_sets_error_status(
    worker_ctx: dict[str, Any], tmp_path: Path
) -> None:
    async with worker_ctx["sessionmaker"]() as session:
        await set_storage_dir(session, str(tmp_path))
    account = await _make_account(worker_ctx)
    sync_module = await _make_sync_module(worker_ctx, account)
    item = await _make_local_item(worker_ctx, sync_module)
    FakeBlinkService.next_error = BlinkError("could not prepare")

    result = await download_sync_module_local_item_job(worker_ctx, str(item.id))
    assert result == "failed: could not prepare"

    async with worker_ctx["sessionmaker"]() as session:
        refreshed = await session.get(SyncModuleLocalItem, item.id)
        assert refreshed is not None
        assert refreshed.status == LocalItemStatus.ERROR
        assert refreshed.last_error == "could not prepare"


# ------------------------------------------------------------------- delete


async def test_delete_job_returns_item_not_found(worker_ctx: dict[str, Any]) -> None:
    result = await delete_sync_module_local_item_job(worker_ctx, str(uuid.uuid4()))
    assert result == "item_not_found"


async def test_delete_job_succeeds(worker_ctx: dict[str, Any]) -> None:
    account = await _make_account(worker_ctx)
    sync_module = await _make_sync_module(worker_ctx, account)
    item = await _make_local_item(worker_ctx, sync_module)

    result = await delete_sync_module_local_item_job(worker_ctx, str(item.id))
    assert result == "ok"

    async with worker_ctx["sessionmaker"]() as session:
        assert await session.get(SyncModuleLocalItem, item.id) is None


async def test_delete_job_reports_failure_and_sets_error_status(worker_ctx: dict[str, Any]) -> None:
    account = await _make_account(worker_ctx)
    sync_module = await _make_sync_module(worker_ctx, account)
    item = await _make_local_item(worker_ctx, sync_module)
    FakeBlinkService.next_error = BlinkError("could not delete")

    result = await delete_sync_module_local_item_job(worker_ctx, str(item.id))
    assert result == "failed: could not delete"

    async with worker_ctx["sessionmaker"]() as session:
        refreshed = await session.get(SyncModuleLocalItem, item.id)
        assert refreshed is not None
        assert refreshed.status == LocalItemStatus.ERROR
        assert refreshed.last_error == "could not delete"


# --------------------------------------------------------- periodic refresh


async def test_periodic_refresh_enqueues_an_eligible_sync_module(
    worker_ctx: dict[str, Any],
) -> None:
    account = await _make_account(worker_ctx)
    sync_module = await _make_sync_module(worker_ctx, account)

    result = await periodic_local_storage_refresh_job(worker_ctx)

    assert result == "enqueued 1"
    worker_ctx["redis"].enqueue_job.assert_any_call(
        REFRESH_LOCAL_STORAGE_JOB_NAME, sync_module_id=str(sync_module.id)
    )


async def test_periodic_refresh_always_reschedules_itself(worker_ctx: dict[str, Any]) -> None:
    await periodic_local_storage_refresh_job(worker_ctx)

    worker_ctx["redis"].enqueue_job.assert_any_call(
        PERIODIC_LOCAL_STORAGE_REFRESH_JOB_NAME,
        _defer_by=PERIODIC_LOCAL_STORAGE_REFRESH_INTERVAL_SECONDS,
    )


async def test_periodic_refresh_skips_a_virtual_non_hub_network(
    worker_ctx: dict[str, Any],
) -> None:
    account = await _make_account(worker_ctx)
    async with worker_ctx["sessionmaker"]() as session:
        session.add(
            SyncModule(
                blink_account_id=account.id,
                network_id="net-mini",
                name="Mini-only network",
                is_physical_hub=False,
                local_storage_active=True,
            )
        )
        await session.commit()

    result = await periodic_local_storage_refresh_job(worker_ctx)
    assert result == "enqueued 0"


async def test_periodic_refresh_skips_an_inactive_local_storage(
    worker_ctx: dict[str, Any],
) -> None:
    account = await _make_account(worker_ctx)
    async with worker_ctx["sessionmaker"]() as session:
        session.add(
            SyncModule(
                blink_account_id=account.id,
                network_id="net-2",
                name="No drive inserted",
                is_physical_hub=True,
                local_storage_active=False,
            )
        )
        await session.commit()

    result = await periodic_local_storage_refresh_job(worker_ctx)
    assert result == "enqueued 0"


async def test_periodic_refresh_skips_a_sync_module_already_refreshing(
    worker_ctx: dict[str, Any],
) -> None:
    account = await _make_account(worker_ctx)
    async with worker_ctx["sessionmaker"]() as session:
        session.add(
            SyncModule(
                blink_account_id=account.id,
                network_id="net-3",
                name="Already refreshing",
                is_physical_hub=True,
                local_storage_active=True,
                local_storage_status=LocalStorageStatus.REFRESHING,
            )
        )
        await session.commit()

    result = await periodic_local_storage_refresh_job(worker_ctx)
    assert result == "enqueued 0"
