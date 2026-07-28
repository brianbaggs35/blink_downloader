"""Moves a downloaded clip's bytes between local disk and whichever cloud
provider it's archived to, and issues time-limited download links.

Thumbnails, vehicle reference photos, and biometrics images are never
touched by any of this - they're cheap to keep local (thumbnails are
regenerable from the clip via ffmpeg; the others are small reference
images), so "archiving" is a clip-video-only concern. See
docs/STORAGE.md.
"""

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.blink.models import Clip, StorageBackend
from app.integrations.cloud import CloudClient, CloudStorageError
from app.integrations.schemas import TemporaryLinkResponse
from app.integrations.service import (
    build_google_drive_client,
    build_onedrive_client,
    build_s3_client,
    get_storage_integration_settings,
)
from app.logs import get_logger
from app.security.crypto import CryptoError, SecretBox
from app.storage.service import ClipStorage, StorageError

logger = get_logger(__name__)

TEMPORARY_LINK_TTL_SECONDS = 3600


class ArchiveError(Exception):
    """A clip could not be archived, restored, or linked."""


async def _client_for(
    session: AsyncSession, backend: StorageBackend, encryption_key: str
) -> CloudClient | None:
    row = await get_storage_integration_settings(session)
    if backend == StorageBackend.S3:
        return build_s3_client(row, encryption_key)
    if backend == StorageBackend.GOOGLE_DRIVE:
        return build_google_drive_client(row, encryption_key)
    if backend == StorageBackend.ONEDRIVE:
        return build_onedrive_client(row, encryption_key)
    return None  # pragma: no cover — callers never pass StorageBackend.LOCAL here.


async def archive_clip(
    session: AsyncSession,
    clip: Clip,
    backend: StorageBackend,
    encryption_key: str,
    local_storage: ClipStorage,
) -> None:
    if backend == StorageBackend.LOCAL:
        raise ArchiveError("local is not an archive destination.")
    if clip.storage_backend != StorageBackend.LOCAL:
        raise ArchiveError("This clip is already archived.")
    if not clip.downloaded_at:
        raise ArchiveError("This clip has not been downloaded yet.")

    client = await _client_for(session, backend, encryption_key)
    if client is None:
        raise ArchiveError(f"{backend.value} is not configured.")

    # clip.storage_path (guaranteed set alongside downloaded_at above), never
    # a recompute - a clip downloaded before clip_path's formula last
    # changed would never resolve correctly through a fresh recompute.
    local_path = Path(clip.storage_path)  # type: ignore[arg-type]
    try:
        data = await asyncio.to_thread(local_path.read_bytes)
    except OSError as exc:
        raise ArchiveError(f"Could not read the local clip file: {exc}") from exc

    try:
        remote_key = await client.upload(f"{clip.id}.mp4", data)
    except CloudStorageError as exc:
        raise ArchiveError(str(exc)) from exc

    try:
        await local_storage.delete(local_path)
    except StorageError as exc:
        # Non-fatal: the remote copy already exists and is now the
        # canonical one - a leftover local file is just wasted disk space,
        # not a correctness problem.
        logger.warning("archive.local_cleanup_failed", clip_id=str(clip.id), error=str(exc))

    clip.storage_backend = backend
    clip.storage_path = remote_key
    await session.commit()


async def restore_clip(
    session: AsyncSession,
    clip: Clip,
    encryption_key: str,
    local_storage: ClipStorage,
) -> None:
    if clip.storage_backend == StorageBackend.LOCAL:
        raise ArchiveError("This clip is already local.")
    if not clip.storage_path:
        raise ArchiveError("This clip has no archived copy to restore.")

    client = await _client_for(session, clip.storage_backend, encryption_key)
    if client is None:
        raise ArchiveError(f"{clip.storage_backend.value} is not configured.")

    try:
        data = await client.download(clip.storage_path)
    except CloudStorageError as exc:
        raise ArchiveError(str(exc)) from exc

    # A genuinely fresh write (the clip is currently NOT local, being
    # restored TO local), so the current clip_path formula applies - unlike
    # archive_clip above, there's no historical reference to preserve here.
    local_path = local_storage.clip_path(clip.camera_id, clip.id, clip.recorded_at)
    try:
        await local_storage.write(local_path, data)
    except StorageError as exc:
        raise ArchiveError(f"Could not write the restored clip locally: {exc}") from exc

    remote_key = clip.storage_path
    try:
        await client.delete(remote_key)
    except CloudStorageError as exc:
        # Non-fatal: the clip is already safely restored locally - a
        # leftover remote copy just means it isn't cleaned up yet.
        logger.warning("archive.remote_cleanup_failed", clip_id=str(clip.id), error=str(exc))

    clip.storage_backend = StorageBackend.LOCAL
    clip.storage_path = str(local_path)
    await session.commit()


async def create_temporary_link(
    session: AsyncSession, clip: Clip, encryption_key: str, *, download_base_url: str
) -> TemporaryLinkResponse:
    if clip.storage_backend == StorageBackend.LOCAL:
        raise ArchiveError("This clip is stored locally; download it directly instead.")
    if not clip.storage_path:
        raise ArchiveError("This clip has no archived copy to link to.")

    expires_at = datetime.now(UTC) + timedelta(seconds=TEMPORARY_LINK_TTL_SECONDS)

    if clip.storage_backend == StorageBackend.S3:
        row = await get_storage_integration_settings(session)
        s3_client = build_s3_client(row, encryption_key)
        if s3_client is None:
            raise ArchiveError("S3 is not configured.")
        try:
            url = await s3_client.presigned_url(clip.storage_path, TEMPORARY_LINK_TTL_SECONDS)
        except CloudStorageError as exc:
            raise ArchiveError(str(exc)) from exc
        return TemporaryLinkResponse(url=url, expires_at=expires_at)

    # Google Drive / OneDrive files are never made public - a short-lived,
    # tamper-proof token that /api/storage/download/{token} verifies before
    # proxying the bytes down from the provider using our own stored OAuth
    # credentials, rather than a provider-native "anyone with the link" URL.
    payload = {
        "clip_id": str(clip.id),
        "backend": clip.storage_backend.value,
        "expires_at": expires_at.isoformat(),
    }
    token = SecretBox(encryption_key).encrypt(json.dumps(payload))
    return TemporaryLinkResponse(url=f"{download_base_url}{token}", expires_at=expires_at)


def resolve_temporary_link_token(
    token: str, encryption_key: str
) -> tuple[uuid.UUID, StorageBackend]:
    try:
        payload = json.loads(SecretBox(encryption_key).decrypt(token))
    except CryptoError as exc:
        raise ArchiveError("This link is invalid.") from exc
    expires_at = datetime.fromisoformat(payload["expires_at"])
    if expires_at < datetime.now(UTC):
        raise ArchiveError("This link has expired.")
    return uuid.UUID(payload["clip_id"]), StorageBackend(payload["backend"])
