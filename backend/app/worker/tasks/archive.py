"""Background archive/restore jobs: moving one clip's bytes between local
disk and a cloud provider is a real upload/download, not something to do
on the request-handling thread.
"""

from datetime import timedelta
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
AUTO_ARCHIVE_CLIP_JOB_NAME = "auto_archive_clip"
RESTORE_CLIP_JOB_NAME = "restore_clip"


async def maybe_enqueue_auto_archive(
    ctx: dict[Any, Any], session: AsyncSession, clip: Clip
) -> None:
    """After a clip finishes downloading (and, if auto-analysis is on,
    being analyzed), moves it off local disk when Settings > Storage's
    "auto-archive new downloads" is set to a cloud provider - the same
    archive_clip the Storage tab's manual archive action uses, just
    triggered automatically instead of by an admin's click.

    A configured auto_archive_after_days delay is handled by deferring
    auto_archive_clip_job rather than baking `backend` into this enqueue
    the way the immediate path does - a days-long deferral should reflect
    whatever the admin's settings are by the time it actually fires (they
    may have switched providers, or turned auto-archive off entirely),
    not replay a decision that's since gone stale."""
    if clip.storage_backend != StorageBackend.LOCAL or clip.downloaded_at is None:
        return
    row = await get_storage_integration_settings(session)
    if row.auto_archive_backend == StorageBackend.LOCAL:
        return
    if row.auto_archive_after_days:
        await ctx["redis"].enqueue_job(
            AUTO_ARCHIVE_CLIP_JOB_NAME,
            clip_id=str(clip.id),
            _defer_by=timedelta(days=row.auto_archive_after_days),
        )
    else:
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
                StorageBackend(backend),
                settings.encryption_key,
                storage,
            )
        except ArchiveError as exc:
            logger.warning("archive.failed", clip_id=clip_id, backend=backend, error=str(exc))
            return f"failed: {exc}"
        logger.info("archive.completed", clip_id=clip_id, backend=backend)
        return "ok"


async def auto_archive_clip_job(ctx: dict[Any, Any], clip_id: str) -> str:
    """The deferred counterpart to archive_clip_job for a configured
    auto_archive_after_days delay - re-reads current settings when the
    delay elapses rather than trusting whatever was true back when the
    delay was scheduled, since an admin could have switched providers or
    turned auto-archive off entirely in the meantime."""
    settings = get_settings()
    sessionmaker: async_sessionmaker[AsyncSession] = ctx["sessionmaker"]
    async with sessionmaker() as session:
        clip = await session.get(Clip, UUID(clip_id))
        if clip is None:
            logger.info("archive.auto_skipped_missing_clip", clip_id=clip_id)
            return "clip_not_found"
        if clip.storage_backend != StorageBackend.LOCAL:
            logger.info("archive.auto_skipped_already_archived", clip_id=clip_id)
            return "skipped"
        row = await get_storage_integration_settings(session)
        if row.auto_archive_backend == StorageBackend.LOCAL:
            logger.info("archive.auto_skipped_disabled", clip_id=clip_id)
            return "skipped"
        storage = get_clip_storage(await resolve_storage_dir(session, settings))
        try:
            await archive_clip(
                session,
                clip,
                row.auto_archive_backend,
                settings.encryption_key,
                storage,
            )
        except ArchiveError as exc:
            logger.warning(
                "archive.auto_failed",
                clip_id=clip_id,
                backend=row.auto_archive_backend.value,
                error=str(exc),
            )
            return f"failed: {exc}"
        logger.info(
            "archive.auto_completed", clip_id=clip_id, backend=row.auto_archive_backend.value
        )
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
            await restore_clip(session, clip, settings.encryption_key, storage)
        except ArchiveError as exc:
            logger.warning("restore.failed", clip_id=clip_id, error=str(exc))
            return f"failed: {exc}"
        logger.info("restore.completed", clip_id=clip_id)
        return "ok"
