"""Per-clip download: fetch bytes from Blink, write to storage, probe metadata.

The clip file itself is the deliverable; duration/thumbnail are best-effort
enrichment that must never roll back an otherwise-successful download.
"""

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.blink.models import BlinkAccount, BlinkAccountStatus, Camera, Clip
from app.blink.service import BlinkAuthError, BlinkError, BlinkMediaItem, BlinkPyService
from app.config import get_settings
from app.logs import get_logger
from app.security.crypto import SecretBox
from app.settings.service import resolve_storage_dir
from app.storage.service import StorageError, get_clip_storage
from app.video.ffmpeg import FfmpegError, generate_thumbnail, probe_duration_seconds
from app.worker.tasks.analyze import ANALYZE_JOB_NAME
from app.worker.tasks.archive import maybe_enqueue_auto_archive

logger = get_logger(__name__)

DOWNLOAD_JOB_NAME = "download_clip"


async def download_clip(ctx: dict[Any, Any], clip_id: str, auto_analyze: bool = True) -> str:
    settings = get_settings()
    sessionmaker: async_sessionmaker[AsyncSession] = ctx["sessionmaker"]
    async with sessionmaker() as session:
        clip = await session.get(Clip, UUID(clip_id))
        if clip is None:
            logger.info("blink.download_skipped_missing_clip", clip_id=clip_id)
            return "clip_not_found"
        if clip.downloaded_at is not None:
            return "already_downloaded"

        camera = await session.get(Camera, clip.camera_id)
        if camera is None:  # pragma: no cover — FK guarantees this can't happen
            return "camera_disabled_or_missing"
        if not camera.enabled:
            return "camera_disabled_or_missing"

        account = await session.get(BlinkAccount, camera.blink_account_id)
        if account is None:  # pragma: no cover — FK guarantees this can't happen
            return "account_missing"

        box = SecretBox(settings.encryption_key)
        token_data = json.loads(box.decrypt(account.encrypted_token_data))
        service = BlinkPyService(token_data)
        item = BlinkMediaItem(
            media_id=clip.blink_clip_id,
            camera_name=camera.name,
            created_at=clip.recorded_at,
            deleted=False,
            raw=clip.raw_metadata,
        )
        try:
            data = await service.download_media(item)
        except BlinkAuthError as exc:
            account.status = BlinkAccountStatus.ERROR
            account.last_error = str(exc)
            await session.commit()
            logger.warning("blink.download_auth_failed", clip_id=clip_id, error=str(exc))
            return "auth_error"
        except BlinkError as exc:
            logger.warning("blink.download_failed", clip_id=clip_id, error=str(exc))
            raise  # network/connection blip — let arq retry
        finally:
            await service.close()

        storage_root = await resolve_storage_dir(session, settings)
        storage = get_clip_storage(storage_root)
        clip_path = storage.clip_path(camera.name, clip.id, clip.recorded_at)
        try:
            size = await storage.write(clip_path, data)
        except StorageError as exc:
            logger.error("blink.download_storage_failed", clip_id=clip_id, error=str(exc))
            raise  # disk/permission blip — let arq retry

        clip.storage_path = str(clip_path)
        clip.filename = clip_path.name
        clip.file_size_bytes = size
        clip.downloaded_at = datetime.now(UTC)
        await session.commit()

        try:
            clip.duration_seconds = await probe_duration_seconds(clip_path)
            thumb_path = storage.thumbnail_path(camera.name, clip.id, clip.recorded_at)
            clip.thumbnail_generated = await generate_thumbnail(clip_path, thumb_path)
            if clip.thumbnail_generated:
                clip.thumbnail_path = str(thumb_path)
        except FfmpegError as exc:
            # The clip itself downloaded fine; a broken ffmpeg install should
            # not make that look like a failed job.
            logger.error("blink.metadata_probe_failed", clip_id=clip_id, error=str(exc))
        await session.commit()

        if auto_analyze:
            await ctx["redis"].enqueue_job(ANALYZE_JOB_NAME, clip_id=clip_id)
        else:
            # No analysis job will run to trigger this afterward - do it
            # directly, since the clip is otherwise done with local disk.
            await maybe_enqueue_auto_archive(ctx, session, clip)
        logger.info(
            "blink.download_completed", clip_id=clip_id, bytes=size, auto_analyze=auto_analyze
        )
        return "ok"
