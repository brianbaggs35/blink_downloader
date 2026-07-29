"""Background Sync Module local (USB) storage jobs: refreshing the device's
manifest, and preparing+downloading or deleting one clip, all involve real
blinkpy calls with their own internal retry/backoff - not something to do on
the request-handling thread.

Mirrors app.worker.tasks.archive's shape: each job is one discrete, whole
unit of work, so a Blink-side failure is reported as a descriptive "failed"
result (with the row's own status/last_error set for the UI to show) rather
than re-raised for arq to blindly retry - an admin re-triggering refresh/
download/delete from the UI is the natural retry path here, same as
Storage's manual archive/restore actions.
"""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.blink.service import BlinkError
from app.config import get_settings
from app.logs import get_logger
from app.settings.service import resolve_storage_dir
from app.storage.service import get_clip_storage
from app.sync_module.models import (
    LocalItemStatus,
    LocalStorageStatus,
    SyncModule,
    SyncModuleLocalItem,
)
from app.sync_module.service import (
    delete_local_storage_item,
    download_local_storage_item,
    refresh_local_storage_manifest,
)

logger = get_logger(__name__)

REFRESH_LOCAL_STORAGE_JOB_NAME = "refresh_sync_module_local_storage"
DOWNLOAD_LOCAL_ITEM_JOB_NAME = "download_sync_module_local_item"
DELETE_LOCAL_ITEM_JOB_NAME = "delete_sync_module_local_item"


async def refresh_sync_module_local_storage_job(ctx: dict[Any, Any], sync_module_id: str) -> str:
    settings = get_settings()
    sessionmaker: async_sessionmaker[AsyncSession] = ctx["sessionmaker"]
    async with sessionmaker() as session:
        sync_module = await session.get(SyncModule, UUID(sync_module_id))
        if sync_module is None:
            logger.info("sync_module.refresh_skipped_missing", sync_module_id=sync_module_id)
            return "sync_module_not_found"
        try:
            await refresh_local_storage_manifest(session, settings, sync_module)
        except BlinkError as exc:
            sync_module.local_storage_status = LocalStorageStatus.ERROR
            sync_module.local_storage_last_error = str(exc)
            await session.commit()
            logger.warning(
                "sync_module.refresh_failed", sync_module_id=sync_module_id, error=str(exc)
            )
            return f"failed: {exc}"
        logger.info("sync_module.refresh_completed", sync_module_id=sync_module_id)
        return "ok"


async def download_sync_module_local_item_job(ctx: dict[Any, Any], item_id: str) -> str:
    settings = get_settings()
    sessionmaker: async_sessionmaker[AsyncSession] = ctx["sessionmaker"]
    async with sessionmaker() as session:
        item = await session.get(SyncModuleLocalItem, UUID(item_id))
        if item is None:
            logger.info("sync_module.download_skipped_missing_item", item_id=item_id)
            return "item_not_found"
        sync_module = await session.get(SyncModule, item.sync_module_id)
        if sync_module is None:  # pragma: no cover — FK guarantees this can't happen
            return "sync_module_not_found"
        storage = get_clip_storage(await resolve_storage_dir(session, settings))
        try:
            await download_local_storage_item(session, settings, storage, item, sync_module)
        except BlinkError as exc:
            item.status = LocalItemStatus.ERROR
            item.last_error = str(exc)
            await session.commit()
            logger.warning("sync_module.download_failed", item_id=item_id, error=str(exc))
            return f"failed: {exc}"
        logger.info("sync_module.download_completed", item_id=item_id)
        return "ok"


async def delete_sync_module_local_item_job(ctx: dict[Any, Any], item_id: str) -> str:
    settings = get_settings()
    sessionmaker: async_sessionmaker[AsyncSession] = ctx["sessionmaker"]
    async with sessionmaker() as session:
        item = await session.get(SyncModuleLocalItem, UUID(item_id))
        if item is None:
            logger.info("sync_module.delete_skipped_missing_item", item_id=item_id)
            return "item_not_found"
        sync_module = await session.get(SyncModule, item.sync_module_id)
        if sync_module is None:  # pragma: no cover — FK guarantees this can't happen
            return "sync_module_not_found"
        try:
            await delete_local_storage_item(session, settings, item, sync_module)
        except BlinkError as exc:
            item.status = LocalItemStatus.ERROR
            item.last_error = str(exc)
            await session.commit()
            logger.warning("sync_module.delete_failed", item_id=item_id, error=str(exc))
            return f"failed: {exc}"
        logger.info("sync_module.delete_completed", item_id=item_id)
        return "ok"
