"""Clip listing, playback/download, and bulk actions.

Viewer accounts may browse, open, and play clips (and their AI analysis) but
nothing that exports, deletes, or costs money — those stay admin-only.
"""

import asyncio
import tempfile
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from app.blink.models import Camera, Clip
from app.blink.schemas import BulkActionResponse, BulkClipIds, ClipListResponse, ClipRead
from app.config import get_settings
from app.db import get_session
from app.logs import get_logger
from app.settings.service import resolve_storage_dir
from app.storage.service import ClipStorage, StorageError, get_clip_storage
from app.users.auth import current_active_user, current_superuser

logger = get_logger(__name__)

router = APIRouter(prefix="/clips", tags=["clips"])

MAX_PAGE_SIZE = 100


@router.get("", response_model=ClipListResponse)
async def list_clips(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_active_user)],
    camera_id: uuid.UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    downloaded_only: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=MAX_PAGE_SIZE),
) -> ClipListResponse:
    stmt = select(Clip)
    count_stmt = select(func.count()).select_from(Clip)
    if camera_id is not None:
        stmt = stmt.where(Clip.camera_id == camera_id)
        count_stmt = count_stmt.where(Clip.camera_id == camera_id)
    if since is not None:
        stmt = stmt.where(Clip.recorded_at >= since)
        count_stmt = count_stmt.where(Clip.recorded_at >= since)
    if until is not None:
        stmt = stmt.where(Clip.recorded_at <= until)
        count_stmt = count_stmt.where(Clip.recorded_at <= until)
    if downloaded_only:
        stmt = stmt.where(Clip.downloaded_at.is_not(None))
        count_stmt = count_stmt.where(Clip.downloaded_at.is_not(None))

    total = (await session.execute(count_stmt)).scalar_one()
    stmt = stmt.order_by(Clip.recorded_at.desc()).offset((page - 1) * page_size).limit(page_size)
    items = (await session.execute(stmt)).scalars().all()
    return ClipListResponse(
        items=[ClipRead.model_validate(c) for c in items],
        total=total,
        page=page,
        page_size=page_size,
    )


async def _get_clip_or_404(session: AsyncSession, clip_id: uuid.UUID) -> Clip:
    clip = await session.get(Clip, clip_id)
    if clip is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clip not found.")
    return clip


@router.get("/{clip_id}", response_model=ClipRead)
async def get_clip(
    clip_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_active_user)],
) -> Clip:
    return await _get_clip_or_404(session, clip_id)


def _clip_file_or_404(path_str: str | None, what: str) -> Path:
    if path_str is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"This clip has no {what} yet."
        )
    path = Path(path_str)
    if not path.exists():
        logger.error("clips.file_missing_on_disk", path=path_str)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"The {what} file is missing from storage.",
        )
    return path


@router.get("/{clip_id}/stream")
async def stream_clip(
    clip_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_active_user)],
) -> FileResponse:
    clip = await _get_clip_or_404(session, clip_id)
    path = _clip_file_or_404(clip.storage_path, "video")
    return FileResponse(path, media_type="video/mp4", content_disposition_type="inline")


@router.get("/{clip_id}/thumbnail")
async def clip_thumbnail(
    clip_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_active_user)],
) -> FileResponse:
    clip = await _get_clip_or_404(session, clip_id)
    if not clip.thumbnail_generated or clip.storage_path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No thumbnail yet.")
    camera = await session.get(Camera, clip.camera_id)
    if camera is None:  # pragma: no cover — FK guarantees this in practice
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No thumbnail yet.")
    storage_root = await resolve_storage_dir(session, get_settings())
    storage = get_clip_storage(storage_root)
    path = _clip_file_or_404(str(storage.thumbnail_path(camera.id, clip.id)), "thumbnail")
    return FileResponse(path, media_type="image/jpeg", content_disposition_type="inline")


@router.get("/{clip_id}/download")
async def download_clip_file(
    clip_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> FileResponse:
    clip = await _get_clip_or_404(session, clip_id)
    path = _clip_file_or_404(clip.storage_path, "video")
    return FileResponse(path, media_type="video/mp4", filename=clip.filename or path.name)


async def _delete_one(session: AsyncSession, storage: ClipStorage, clip: Clip) -> None:
    await storage.delete(storage.clip_path(clip.camera_id, clip.id))
    await storage.delete(storage.thumbnail_path(clip.camera_id, clip.id))
    await session.delete(clip)


@router.delete("/{clip_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_clip(
    clip_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> None:
    clip = await _get_clip_or_404(session, clip_id)
    storage_root = await resolve_storage_dir(session, get_settings())
    storage = get_clip_storage(storage_root)
    try:
        await _delete_one(session, storage, clip)
        await session.commit()
    except StorageError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Could not delete file: {exc}"
        ) from exc


@router.post("/bulk-delete", response_model=BulkActionResponse)
async def bulk_delete_clips(
    payload: BulkClipIds,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> BulkActionResponse:
    storage_root = await resolve_storage_dir(session, get_settings())
    storage = get_clip_storage(storage_root)
    clips = (
        (await session.execute(select(Clip).where(Clip.id.in_(payload.clip_ids)))).scalars().all()
    )
    succeeded = 0
    failed = 0
    for clip in clips:
        try:
            await _delete_one(session, storage, clip)
            succeeded += 1
        except StorageError as exc:
            logger.error("clips.bulk_delete_failed", clip_id=str(clip.id), error=str(exc))
            failed += 1
    failed += len(payload.clip_ids) - len(clips)  # ids that didn't match any clip
    await session.commit()
    return BulkActionResponse(succeeded=succeeded, failed=failed)


def _build_zip(clip_paths: list[tuple[Path, str]]) -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)  # noqa: SIM115
    tmp.close()
    tmp_path = Path(tmp.name)
    with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_STORED) as zf:
        for path, arcname in clip_paths:
            if path.exists():
                zf.write(path, arcname=arcname)
    return tmp_path


@router.post("/bulk-download")
async def bulk_download_clips(
    payload: BulkClipIds,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> FileResponse:
    clips = (
        (await session.execute(select(Clip).where(Clip.id.in_(payload.clip_ids)))).scalars().all()
    )
    downloadable = [c for c in clips if c.storage_path]
    if not downloadable:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="None of the selected clips have been downloaded yet.",
        )

    clip_paths = [
        (Path(c.storage_path), c.filename or f"{c.id}.mp4")  # type: ignore[arg-type]
        for c in downloadable
    ]
    zip_path = await asyncio.to_thread(_build_zip, clip_paths)
    zip_name = f"clips-{datetime.now(UTC):%Y%m%d-%H%M%S}.zip"
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=zip_name,
        background=BackgroundTask(zip_path.unlink, missing_ok=True),
    )
