"""Sync Module CRUD, arm/disarm, per-camera motion toggling, and local (USB)
storage manifest refresh/download/delete.

Mirrors app.livefeed.service's "check disable_blink_network_calls, load the
account, decrypt its token, construct a short-lived BlinkPyService, map
BlinkAuthError to an account-level error, always close()" shape used
throughout this app's Blink integration. The slower local-storage
operations (manifest refresh, prepare+download, delete) deliberately raise
on failure rather than swallowing it into a status field themselves - the
caller (a worker job, see app.worker.tasks.sync_module) owns translating
that into local_storage_status/item.status and deciding whether to retry.
"""

import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.blink.models import BlinkAccount, BlinkAccountStatus, Camera
from app.blink.service import BlinkAuthError, BlinkError, BlinkLocalStorageItem, BlinkPyService
from app.config import Settings
from app.security.crypto import SecretBox
from app.storage.service import ClipStorage
from app.sync_module.models import (
    LocalItemStatus,
    LocalStorageStatus,
    SyncModule,
    SyncModuleLocalItem,
)


class MotionNotSupportedError(Exception):
    """This camera has no independent motion-detection state to toggle
    (a Mini camera, which mirrors its Sync Module's own armed state)."""


async def list_sync_modules(session: AsyncSession) -> Sequence[SyncModule]:
    stmt = select(SyncModule).order_by(SyncModule.name)
    return (await session.execute(stmt)).scalars().all()


async def list_cameras_for_sync_module(
    session: AsyncSession, sync_module: SyncModule
) -> Sequence[Camera]:
    stmt = (
        select(Camera)
        .where(
            Camera.blink_account_id == sync_module.blink_account_id,
            Camera.blink_network_id == sync_module.network_id,
        )
        .order_by(Camera.name)
    )
    return (await session.execute(stmt)).scalars().all()


async def list_local_items(
    session: AsyncSession, sync_module: SyncModule
) -> Sequence[SyncModuleLocalItem]:
    stmt = (
        select(SyncModuleLocalItem)
        .where(SyncModuleLocalItem.sync_module_id == sync_module.id)
        .order_by(SyncModuleLocalItem.recorded_at.desc())
    )
    return (await session.execute(stmt)).scalars().all()


async def _load_account(session: AsyncSession, sync_module: SyncModule) -> BlinkAccount:
    account = await session.get(BlinkAccount, sync_module.blink_account_id)
    if account is None:  # pragma: no cover — FK guarantees this can't happen
        raise BlinkError("No Blink account linked.")
    return account


def _build_service(settings: Settings, account: BlinkAccount) -> BlinkPyService:
    box = SecretBox(settings.encryption_key)
    token_data = json.loads(box.decrypt(account.encrypted_token_data))
    return BlinkPyService(token_data)


async def arm_sync_module(
    session: AsyncSession, settings: Settings, sync_module: SyncModule, armed: bool
) -> SyncModule:
    if settings.disable_blink_network_calls:
        raise BlinkError("Live Blink calls are disabled in this environment.")

    account = await _load_account(session, sync_module)
    service = _build_service(settings, account)
    try:
        await service.set_sync_module_arm(sync_module.network_id, armed)
    except BlinkAuthError as exc:
        account.status = BlinkAccountStatus.ERROR
        account.last_error = str(exc)
        await session.commit()
        raise
    finally:
        await service.close()

    sync_module.armed = armed
    await session.commit()
    await session.refresh(sync_module)
    return sync_module


async def set_camera_motion_detection(
    session: AsyncSession,
    settings: Settings,
    camera: Camera,
    sync_module: SyncModule,
    enabled: bool,
) -> Camera:
    if camera.motion_action_type == "mini":
        raise MotionNotSupportedError(
            "Mini cameras follow the Sync Module's armed state, not an independent toggle."
        )
    if settings.disable_blink_network_calls:
        raise BlinkError("Live Blink calls are disabled in this environment.")

    account = await _load_account(session, sync_module)
    service = _build_service(settings, account)
    try:
        await service.set_camera_motion_detection(
            sync_module.network_id, camera.blink_camera_id, camera.motion_action_type, enabled
        )
    except BlinkAuthError as exc:
        account.status = BlinkAccountStatus.ERROR
        account.last_error = str(exc)
        await session.commit()
        raise
    finally:
        await service.close()

    camera.motion_enabled = enabled
    await session.commit()
    await session.refresh(camera)
    return camera


async def bulk_set_camera_motion_detection(
    session: AsyncSession,
    settings: Settings,
    sync_module: SyncModule,
    cameras: Sequence[Camera],
    enabled: bool,
) -> tuple[int, int]:
    """Applies to every non-Mini camera under this sync module in one
    shared BlinkPyService (one auth handshake, not one per camera). Minis
    are skipped entirely - they count toward neither succeeded nor failed.
    Returns (succeeded, failed)."""
    applicable = [camera for camera in cameras if camera.motion_action_type != "mini"]
    if not applicable:
        return 0, 0
    if settings.disable_blink_network_calls:
        raise BlinkError("Live Blink calls are disabled in this environment.")

    account = await _load_account(session, sync_module)
    service = _build_service(settings, account)
    succeeded = 0
    failed = 0
    try:
        for index, camera in enumerate(applicable):
            try:
                await service.set_camera_motion_detection(
                    sync_module.network_id,
                    camera.blink_camera_id,
                    camera.motion_action_type,
                    enabled,
                )
            except BlinkAuthError as exc:
                # A bad/expired token fails identically for every remaining
                # camera - stop retrying it and count the rest as failed
                # too, rather than repeating the same failing handshake.
                account.status = BlinkAccountStatus.ERROR
                account.last_error = str(exc)
                failed += len(applicable) - index
                break
            except BlinkError:
                failed += 1
                continue
            camera.motion_enabled = enabled
            succeeded += 1
    finally:
        await service.close()
    await session.commit()
    return succeeded, failed


async def refresh_local_storage_manifest(
    session: AsyncSession, settings: Settings, sync_module: SyncModule
) -> None:
    sync_module.local_storage_status = LocalStorageStatus.REFRESHING
    sync_module.local_storage_manifest_requested_at = datetime.now(UTC)
    await session.commit()

    if settings.disable_blink_network_calls:
        raise BlinkError("Live Blink calls are disabled in this environment.")

    account = await _load_account(session, sync_module)
    service = _build_service(settings, account)
    try:
        manifest = await service.refresh_local_storage_manifest(sync_module.network_id)
    except BlinkAuthError as exc:
        account.status = BlinkAccountStatus.ERROR
        account.last_error = str(exc)
        await session.commit()
        raise
    finally:
        await service.close()

    await _reconcile_local_items(session, sync_module.id, manifest.items)
    sync_module.local_storage_manifest_id = manifest.manifest_id
    sync_module.local_storage_status = LocalStorageStatus.IDLE
    sync_module.local_storage_last_error = None
    sync_module.local_storage_manifest_refreshed_at = datetime.now(UTC)
    await session.commit()


async def _reconcile_local_items(
    session: AsyncSession,
    sync_module_id: uuid.UUID,
    manifest_items: Sequence[BlinkLocalStorageItem],
) -> None:
    """Deliberately ORM-only (no Core-level upsert): this app's sessions use
    expire_on_commit=False, and mixing a Core-level INSERT/UPDATE with
    ORM-mapped objects already in this session's identity map leaves stale
    in-memory attributes behind with no reliable way to refresh just the
    affected rows. Fetching every existing row once and mutating those same
    Python objects (or adding new ones) sidesteps that entirely - the extra
    round trip is a non-issue at the scale of one Sync Module's USB drive."""
    manifest_item_ids = {item.item_id for item in manifest_items}

    cameras_stmt = (
        select(Camera.id, Camera.name)
        .join(SyncModule, Camera.blink_network_id == SyncModule.network_id)
        .where(SyncModule.id == sync_module_id)
    )
    cameras_by_name = {
        name.lower(): camera_id for camera_id, name in (await session.execute(cameras_stmt)).all()
    }

    existing_stmt = select(SyncModuleLocalItem).where(
        SyncModuleLocalItem.sync_module_id == sync_module_id
    )
    existing_by_item_id = {
        row.blink_item_id: row for row in (await session.execute(existing_stmt)).scalars().all()
    }

    for item in manifest_items:
        camera_id = cameras_by_name.get(item.camera_name.lower())
        row = existing_by_item_id.get(item.item_id)
        if row is None:
            session.add(
                SyncModuleLocalItem(
                    sync_module_id=sync_module_id,
                    camera_id=camera_id,
                    camera_name=item.camera_name,
                    blink_item_id=item.item_id,
                    recorded_at=item.recorded_at,
                    size_bytes=item.size_bytes,
                    present_on_device=True,
                )
            )
            continue
        row.camera_id = camera_id
        row.camera_name = item.camera_name
        row.size_bytes = item.size_bytes
        row.present_on_device = True

    for blink_item_id, row in existing_by_item_id.items():
        if blink_item_id in manifest_item_ids:
            continue
        # Gone from the device: a never-downloaded row is just noise now
        # (nothing lost by dropping it); an already-downloaded row is kept
        # since we still have our own copy, just no longer on the device.
        if row.status == LocalItemStatus.AVAILABLE:
            await session.delete(row)
        else:
            row.present_on_device = False
    await session.flush()


async def download_local_storage_item(
    session: AsyncSession,
    settings: Settings,
    storage: ClipStorage,
    item: SyncModuleLocalItem,
    sync_module: SyncModule,
) -> None:
    if sync_module.sync_id is None or sync_module.local_storage_manifest_id is None:
        raise BlinkError("No local storage manifest available yet - refresh first.")

    item.status = LocalItemStatus.PREPARING
    await session.commit()

    if settings.disable_blink_network_calls:
        raise BlinkError("Live Blink calls are disabled in this environment.")

    account = await _load_account(session, sync_module)
    service = _build_service(settings, account)
    try:
        await service.prepare_local_storage_clip(
            sync_module.network_id,
            sync_module.sync_id,
            sync_module.local_storage_manifest_id,
            item.blink_item_id,
        )
        item.status = LocalItemStatus.DOWNLOADING
        await session.commit()
        data = await service.download_local_storage_clip(
            sync_module.network_id,
            sync_module.sync_id,
            sync_module.local_storage_manifest_id,
            item.blink_item_id,
        )
    except BlinkAuthError as exc:
        account.status = BlinkAccountStatus.ERROR
        account.last_error = str(exc)
        await session.commit()
        raise
    finally:
        await service.close()

    path = storage.sync_module_clip_path(sync_module.id, item.id, item.recorded_at)
    await storage.write(path, data)
    item.storage_path = str(path)
    item.downloaded_at = datetime.now(UTC)
    item.status = LocalItemStatus.DOWNLOADED
    item.last_error = None
    await session.commit()


async def delete_local_storage_item(
    session: AsyncSession, settings: Settings, item: SyncModuleLocalItem, sync_module: SyncModule
) -> None:
    if sync_module.sync_id is None or sync_module.local_storage_manifest_id is None:
        raise BlinkError("No local storage manifest available yet - refresh first.")
    if settings.disable_blink_network_calls:
        raise BlinkError("Live Blink calls are disabled in this environment.")

    account = await _load_account(session, sync_module)
    service = _build_service(settings, account)
    try:
        deleted = await service.delete_local_storage_clip(
            sync_module.network_id,
            sync_module.sync_id,
            sync_module.local_storage_manifest_id,
            item.blink_item_id,
        )
    except BlinkAuthError as exc:
        account.status = BlinkAccountStatus.ERROR
        account.last_error = str(exc)
        await session.commit()
        raise
    finally:
        await service.close()

    if not deleted:
        raise BlinkError("Could not delete the clip from the Sync Module.")

    await session.delete(item)
    await session.commit()
