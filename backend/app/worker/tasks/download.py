"""Per-clip download: fetch bytes from Blink, write to storage, probe metadata.

The clip file itself is the deliverable; duration/thumbnail are best-effort
enrichment that must never roll back an otherwise-successful download.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.blink.models import BlinkAccount, BlinkAccountStatus, Camera, Clip
from app.blink.service import BlinkAuthError, BlinkError, BlinkMediaItem, BlinkPyService
from app.config import get_settings
from app.logs import get_logger
from app.security.crypto import SecretBox
from app.settings.service import resolve_storage_dir
from app.storage.service import ClipStorage, StorageError, get_clip_storage
from app.video.ffmpeg import FfmpegError, generate_thumbnail, probe_duration_seconds
from app.worker.tasks.analyze import ANALYZE_JOB_NAME
from app.worker.tasks.archive import maybe_enqueue_auto_archive

logger = get_logger(__name__)

DOWNLOAD_JOB_NAME = "download_clip"

_DOWNLOAD_PROBE_MAX_ATTEMPTS = 3
"""download_media() has no status/Content-Length validation of its own, so
a transient truncated transfer is silently accepted as a "successful"
download otherwise - matching the visual signature reported (a thumbnail
with a clean top fading into corruption, exactly what decoding a
truncated H.264 stream looks like). Bounded retries with fresh bytes give
a one-off network blip a few chances to self-heal; still accepted after
exhausting them, so a file ffprobe genuinely can't parse for unrelated
reasons never gets stuck undownloaded forever."""


async def _download_and_verify(
    service: BlinkPyService, item: BlinkMediaItem, storage: ClipStorage, clip_path: Path
) -> tuple[int, float | None]:
    """Downloads+writes the clip, retrying with fresh bytes when the
    result fails ffprobe, up to _DOWNLOAD_PROBE_MAX_ATTEMPTS. FfmpegError
    from the probe itself (ffmpeg missing/broken, not a corrupt file)
    breaks the loop immediately - retrying can't fix a broken ffmpeg
    install, and the download itself already succeeded."""
    size = 0
    duration: float | None = None
    for attempt in range(_DOWNLOAD_PROBE_MAX_ATTEMPTS):
        data = await service.download_media(item)
        size = await storage.write(clip_path, data)
        try:
            duration = await probe_duration_seconds(clip_path)
        except FfmpegError as exc:
            logger.error("blink.metadata_probe_failed", media_id=item.media_id, error=str(exc))
            break
        if duration is not None:
            break
        if attempt < _DOWNLOAD_PROBE_MAX_ATTEMPTS - 1:
            logger.warning(
                "blink.download_probe_failed_retrying",
                media_id=item.media_id,
                attempt=attempt + 1,
            )
    return size, duration


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
        storage_root = await resolve_storage_dir(session, settings)
        storage = get_clip_storage(storage_root)
        clip_path = storage.clip_path(camera.name, clip.id, clip.recorded_at)
        try:
            size, duration = await _download_and_verify(service, item, storage, clip_path)
        except BlinkAuthError as exc:
            account.status = BlinkAccountStatus.ERROR
            account.last_error = str(exc)
            await session.commit()
            logger.warning("blink.download_auth_failed", clip_id=clip_id, error=str(exc))
            return "auth_error"
        except BlinkError as exc:
            logger.warning("blink.download_failed", clip_id=clip_id, error=str(exc))
            raise  # network/connection blip — let arq retry
        except StorageError as exc:
            logger.error("blink.download_storage_failed", clip_id=clip_id, error=str(exc))
            raise  # disk/permission blip — let arq retry
        finally:
            await service.close()

        clip.storage_path = str(clip_path)
        clip.filename = clip_path.name
        clip.file_size_bytes = size
        clip.duration_seconds = duration
        clip.downloaded_at = datetime.now(UTC)
        await session.commit()

        # generate_thumbnail() never raises (it returns False for an
        # unreadable/corrupt source, same policy as probe_duration_seconds -
        # see its own docstring) - no exception handling needed here.
        thumb_path = storage.thumbnail_path(camera.name, clip.id, clip.recorded_at)
        clip.thumbnail_generated = await generate_thumbnail(clip_path, thumb_path)
        if clip.thumbnail_generated:
            clip.thumbnail_path = str(thumb_path)
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
