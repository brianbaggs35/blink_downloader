"""Background archive/restore jobs: moving one clip's bytes between local
disk and a cloud provider is a real upload/download, not something to do
on the request-handling thread.
"""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.blink.models import Clip, StorageBackend
from app.config import get_settings
from app.integrations.archive import ArchiveError, archive_clip, restore_clip
from app.integrations.service import get_storage_integration_settings
from app.logs import get_logger
from app.settings.service import resolve_storage_dir
from app.storage.service import get_clip_storage

logger = get_logger(__name__)

ARCHIVE_CLIP_JOB_NAME = "archive_clip"
RESTORE_CLIP_JOB_NAME = "restore_clip"


async def maybe_enqueue_auto_archive(
    ctx: dict[Any, Any], session: AsyncSession, clip: Clip
) -> None:
    """After a clip finishes downloading (and, if auto-analysis is on,
    being analyzed), moves it off local disk when Settings > Archived's
    "auto-archive new downloads" is set to a cloud provider - the same
    archive_clip the Storage tab's manual archive action uses, just
    triggered automatically instead of by an admin's click."""
    if clip.storage_backend != StorageBackend.LOCAL or clip.downloaded_at is None:
        return
    row = await get_storage_integration_settings(session)
    if row.auto_archive_backend == StorageBackend.LOCAL:
        return
    await ctx["redis"].enqueue_job(
        ARCHIVE_CLIP_JOB_NAME, clip_id=str(clip.id), backend=row.auto_archive_backend.value
    )


async def archive_clip_job(ctx: dict[Any, Any], clip_id: str, backend: str) -> str:
    settings = get_settings()
    sessionmaker: async_sessionmaker[AsyncSession] = ctx["sessionmaker"]
    async with sessionmaker() as session:
        clip = await session.get(Clip, UUID(clip_id))
        if clip is None:
            logger.info("archive.skipped_missing_clip", clip_id=clip_id)
            return "clip_not_found"
        storage = get_clip_storage(await resolve_storage_dir(session, settings))
        try:
            await archive_clip(
                session,
                clip,
                clip.camera_id,
                StorageBackend(backend),
                settings.encryption_key,
                storage,
            )
        except ArchiveError as exc:
            logger.warning("archive.failed", clip_id=clip_id, backend=backend, error=str(exc))
            return f"failed: {exc}"
        logger.info("archive.completed", clip_id=clip_id, backend=backend)
        return "ok"


async def restore_clip_job(ctx: dict[Any, Any], clip_id: str) -> str:
    settings = get_settings()
    sessionmaker: async_sessionmaker[AsyncSession] = ctx["sessionmaker"]
    async with sessionmaker() as session:
        clip = await session.get(Clip, UUID(clip_id))
        if clip is None:
            logger.info("restore.skipped_missing_clip", clip_id=clip_id)
            return "clip_not_found"
        storage = get_clip_storage(await resolve_storage_dir(session, settings))
        try:
            await restore_clip(session, clip, clip.camera_id, settings.encryption_key, storage)
        except ArchiveError as exc:
            logger.warning("restore.failed", clip_id=clip_id, error=str(exc))
            return f"failed: {exc}"
        logger.info("restore.completed", clip_id=clip_id)
        return "ok"
