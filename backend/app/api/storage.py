"""Storage tab: usage summary, archive/restore actions, and secure
temporary download links for clips archived to a cloud provider.

Viewing (summary) is open to any signed-in household member, matching
Library's own clip listing; archiving, restoring, and generating links
all touch external accounts/credentials or move real bytes around, so
they're admin-only, matching bulk-delete's own gating.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.blink.models import Clip, StorageBackend
from app.config import get_settings
from app.db import get_session
from app.integrations.archive import (
    ArchiveError,
    create_temporary_link,
    resolve_temporary_link_token,
)
from app.integrations.cloud import CloudStorageError
from app.integrations.models import StorageIntegrationSettings
from app.integrations.schemas import (
    ArchiveClipsRequest,
    BackendStorageSummary,
    RestoreClipsRequest,
    StorageSummaryResponse,
    TemporaryLinkResponse,
)
from app.integrations.service import (
    build_google_drive_client,
    build_onedrive_client,
    build_s3_client,
    get_storage_integration_settings,
)
from app.logs import get_logger
from app.settings.service import get_app_settings
from app.users.auth import current_active_user, current_superuser
from app.worker.tasks.archive import ARCHIVE_CLIP_JOB_NAME, RESTORE_CLIP_JOB_NAME

logger = get_logger(__name__)

router = APIRouter(prefix="/storage", tags=["storage"])


def _configured_backends(
    row: StorageIntegrationSettings, encryption_key: str
) -> set[StorageBackend]:
    configured: set[StorageBackend] = set()
    if build_s3_client(row, encryption_key) is not None:
        configured.add(StorageBackend.S3)
    if build_google_drive_client(row, encryption_key) is not None:
        configured.add(StorageBackend.GOOGLE_DRIVE)
    if build_onedrive_client(row, encryption_key) is not None:
        configured.add(StorageBackend.ONEDRIVE)
    return configured


@router.get("/summary", response_model=StorageSummaryResponse)
async def get_storage_summary(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_active_user)],
) -> StorageSummaryResponse:
    rows = await session.execute(
        select(
            Clip.storage_backend,
            func.count(),
            func.coalesce(func.sum(Clip.file_size_bytes), 0),
        )
        .where(Clip.downloaded_at.is_not(None))
        .group_by(Clip.storage_backend)
    )
    by_backend = [
        BackendStorageSummary(backend=backend, clip_count=count, total_bytes=int(total_bytes))
        for backend, count, total_bytes in rows
    ]
    app_settings = await get_app_settings(session)
    integration_settings = await get_storage_integration_settings(session)
    configured = _configured_backends(integration_settings, get_settings().encryption_key)
    return StorageSummaryResponse(
        by_backend=by_backend,
        total_clips=sum(item.clip_count for item in by_backend),
        total_bytes=sum(item.total_bytes for item in by_backend),
        local_quota_bytes=app_settings.local_storage_quota_bytes,
        connected_backends=[StorageBackend.LOCAL, *sorted(configured, key=lambda b: b.value)],
    )


@router.post("/archive")
async def archive_clips(
    payload: ArchiveClipsRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> dict[str, int]:
    settings_row = await get_storage_integration_settings(session)
    if payload.backend not in _configured_backends(settings_row, get_settings().encryption_key):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{payload.backend.value} is not configured.",
        )
    clips = (
        (await session.execute(select(Clip).where(Clip.id.in_(payload.clip_ids)))).scalars().all()
    )
    queued = 0
    failed = 0
    for clip in clips:
        if clip.storage_backend == StorageBackend.LOCAL and clip.downloaded_at is not None:
            await request.app.state.arq_redis.enqueue_job(
                ARCHIVE_CLIP_JOB_NAME, clip_id=str(clip.id), backend=payload.backend.value
            )
            queued += 1
        else:
            failed += 1
    failed += len(payload.clip_ids) - len(clips)
    return {"succeeded": queued, "failed": failed}


@router.post("/restore")
async def restore_clips(
    payload: RestoreClipsRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> dict[str, int]:
    clips = (
        (await session.execute(select(Clip).where(Clip.id.in_(payload.clip_ids)))).scalars().all()
    )
    queued = 0
    failed = 0
    for clip in clips:
        if clip.storage_backend != StorageBackend.LOCAL:
            await request.app.state.arq_redis.enqueue_job(
                RESTORE_CLIP_JOB_NAME, clip_id=str(clip.id)
            )
            queued += 1
        else:
            failed += 1
    failed += len(payload.clip_ids) - len(clips)
    return {"succeeded": queued, "failed": failed}


async def _get_clip_or_404(session: AsyncSession, clip_id: uuid.UUID) -> Clip:
    clip = await session.get(Clip, clip_id)
    if clip is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clip not found.")
    return clip


@router.post("/clips/{clip_id}/link", response_model=TemporaryLinkResponse)
async def get_temporary_link(
    clip_id: uuid.UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_active_user)],
) -> TemporaryLinkResponse:
    clip = await _get_clip_or_404(session, clip_id)
    download_base_url = f"{request.base_url}api/storage/download/"
    try:
        return await create_temporary_link(
            session, clip, get_settings().encryption_key, download_base_url=download_base_url
        )
    except ArchiveError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/download/{token}", name="download_archived_clip")
async def download_archived_clip(
    token: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> StreamingResponse:
    """Proxies a Google Drive/OneDrive clip down using our own stored OAuth
    credentials - the token itself (not a login session) is the bearer
    proof of a time-limited authorization to fetch this one clip, the same
    trust model as an S3 presigned URL."""
    try:
        clip_id, backend = resolve_temporary_link_token(token, get_settings().encryption_key)
    except ArchiveError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    clip = await _get_clip_or_404(session, clip_id)
    if clip.storage_backend != backend or not clip.storage_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clip not found.")

    settings_row = await get_storage_integration_settings(session)
    encryption_key = get_settings().encryption_key
    client = (
        build_google_drive_client(settings_row, encryption_key)
        if backend == StorageBackend.GOOGLE_DRIVE
        else build_onedrive_client(settings_row, encryption_key)
    )
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"{backend.value} is not configured."
        )
    try:
        data = await client.download(clip.storage_path)
    except CloudStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Could not fetch this clip: {exc}"
        ) from exc

    filename = clip.filename or f"{clip.id}.mp4"
    return StreamingResponse(
        iter([data]),
        media_type="video/mp4",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
