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
from app.logs import get_logger
from app.settings.service import resolve_storage_dir
from app.storage.service import get_clip_storage

logger = get_logger(__name__)

ARCHIVE_CLIP_JOB_NAME = "archive_clip"
RESTORE_CLIP_JOB_NAME = "restore_clip"


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
