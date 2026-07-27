"""Clip listing, playback/download, and bulk actions.

Viewer accounts may browse, open, and play clips (and their AI analysis) but
nothing that exports, deletes, or costs money — those stay admin-only.
"""

import asyncio
import tempfile
import uuid
import zipfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from app.ai.learning import record_feedback
from app.ai.models import Analysis, Feedback
from app.ai.schemas import AnalysisRead, FeedbackCreate, FeedbackRead
from app.biometrics.models import Person, RecognizedFace
from app.biometrics.schemas import RecognizedPersonRead
from app.blink.models import Camera, Clip, StorageBackend
from app.blink.schemas import BulkActionResponse, BulkClipIds, ClipListResponse, ClipRead
from app.config import get_settings
from app.db import get_session
from app.integrations.cloud import CloudClient, CloudStorageError
from app.integrations.service import (
    build_google_drive_client,
    build_onedrive_client,
    build_s3_client,
    get_storage_integration_settings,
)
from app.logs import get_logger
from app.settings.service import resolve_storage_dir
from app.storage.service import ClipStorage, StorageError, get_clip_storage
from app.users.auth import current_active_user, current_superuser
from app.users.models import User
from app.worker.tasks.analyze import ANALYZE_JOB_NAME

logger = get_logger(__name__)

router = APIRouter(prefix="/clips", tags=["clips"])

MAX_PAGE_SIZE = 100


async def _recognized_people_by_clip(
    session: AsyncSession, clip_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[RecognizedPersonRead]]:
    if not clip_ids:
        return {}
    stmt = (
        select(RecognizedFace.clip_id, Person.id, Person.name)
        .join(Person, RecognizedFace.person_id == Person.id)
        .where(RecognizedFace.clip_id.in_(clip_ids))
        .order_by(Person.name)
    )
    by_clip: dict[uuid.UUID, list[RecognizedPersonRead]] = {}
    for row in await session.execute(stmt):
        by_clip.setdefault(row.clip_id, []).append(RecognizedPersonRead(id=row.id, name=row.name))
    return by_clip


def _clip_read(clip: Clip, recognized_people: list[RecognizedPersonRead]) -> ClipRead:
    return ClipRead(
        id=clip.id,
        camera_id=clip.camera_id,
        recorded_at=clip.recorded_at,
        duration_seconds=clip.duration_seconds,
        file_size_bytes=clip.file_size_bytes,
        downloaded_at=clip.downloaded_at,
        deleted_on_blink=clip.deleted_on_blink,
        thumbnail_generated=clip.thumbnail_generated,
        storage_backend=clip.storage_backend,
        recognized_people=recognized_people,
    )


@router.get("", response_model=ClipListResponse)
async def list_clips(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_active_user)],
    camera_id: uuid.UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    downloaded_only: bool = False,
    recognized_person_id: uuid.UUID | None = None,
    has_recognized_person: bool | None = None,
    storage_backend: StorageBackend | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=MAX_PAGE_SIZE),
) -> ClipListResponse:
    stmt = select(Clip)
    count_stmt = select(func.count()).select_from(Clip)
    if camera_id is not None:
        stmt = stmt.where(Clip.camera_id == camera_id)
        count_stmt = count_stmt.where(Clip.camera_id == camera_id)
    if storage_backend is not None:
        stmt = stmt.where(Clip.storage_backend == storage_backend)
        count_stmt = count_stmt.where(Clip.storage_backend == storage_backend)
    if since is not None:
        stmt = stmt.where(Clip.recorded_at >= since)
        count_stmt = count_stmt.where(Clip.recorded_at >= since)
    if until is not None:
        stmt = stmt.where(Clip.recorded_at <= until)
        count_stmt = count_stmt.where(Clip.recorded_at <= until)
    if downloaded_only:
        stmt = stmt.where(Clip.downloaded_at.is_not(None))
        count_stmt = count_stmt.where(Clip.downloaded_at.is_not(None))
    if recognized_person_id is not None:
        recognized_clip_ids = select(RecognizedFace.clip_id).where(
            RecognizedFace.person_id == recognized_person_id
        )
        stmt = stmt.where(Clip.id.in_(recognized_clip_ids))
        count_stmt = count_stmt.where(Clip.id.in_(recognized_clip_ids))
    if has_recognized_person is not None:
        any_recognized_clip_ids = select(RecognizedFace.clip_id)
        condition = Clip.id.in_(any_recognized_clip_ids)
        if not has_recognized_person:
            condition = ~condition
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)

    total = (await session.execute(count_stmt)).scalar_one()
    stmt = stmt.order_by(Clip.recorded_at.desc()).offset((page - 1) * page_size).limit(page_size)
    items = (await session.execute(stmt)).scalars().all()
    recognized_by_clip = await _recognized_people_by_clip(session, [c.id for c in items])
    return ClipListResponse(
        items=[_clip_read(c, recognized_by_clip.get(c.id, [])) for c in items],
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
) -> ClipRead:
    clip = await _get_clip_or_404(session, clip_id)
    recognized = (await _recognized_people_by_clip(session, [clip.id])).get(clip.id, [])
    return _clip_read(clip, recognized)


async def _get_current_analysis_or_404(session: AsyncSession, clip_id: uuid.UUID) -> Analysis:
    stmt = select(Analysis).where(Analysis.clip_id == clip_id, Analysis.is_current.is_(True))
    analysis = (await session.execute(stmt)).scalar_one_or_none()
    if analysis is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="This clip has not been analyzed yet."
        )
    return analysis


@router.get("/{clip_id}/analysis", response_model=AnalysisRead)
async def get_clip_analysis(
    clip_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_active_user)],
) -> Analysis:
    await _get_clip_or_404(session, clip_id)
    return await _get_current_analysis_or_404(session, clip_id)


@router.post(
    "/{clip_id}/feedback", response_model=FeedbackRead, status_code=status.HTTP_201_CREATED
)
async def submit_feedback(
    clip_id: uuid.UUID,
    payload: FeedbackCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(current_active_user)],
) -> Feedback:
    clip = await _get_clip_or_404(session, clip_id)
    analysis = await _get_current_analysis_or_404(session, clip_id)
    return await record_feedback(session, analysis, clip, user.id, payload.verdict, payload.note)


@router.get("/{clip_id}/feedback", response_model=list[FeedbackRead])
async def list_feedback(
    clip_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_active_user)],
) -> Sequence[Feedback]:
    await _get_clip_or_404(session, clip_id)
    stmt = (
        select(Feedback)
        .join(Analysis, Feedback.analysis_id == Analysis.id)
        .where(Analysis.clip_id == clip_id)
        .order_by(Feedback.created_at.desc())
    )
    return (await session.execute(stmt)).scalars().all()


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


@router.post("/{clip_id}/reanalyze", status_code=status.HTTP_202_ACCEPTED)
async def reanalyze_clip(
    clip_id: uuid.UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> dict[str, str]:
    clip = await _get_clip_or_404(session, clip_id)
    if not clip.storage_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This clip has not been downloaded yet.",
        )
    camera = await session.get(Camera, clip.camera_id)
    if camera is not None and not camera.enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This clip's camera is disabled — enable it in Settings to analyze its clips.",
        )
    await request.app.state.arq_redis.enqueue_job(ANALYZE_JOB_NAME, clip_id=str(clip.id))
    return {"status": "queued"}


@router.post("/bulk-analyze", response_model=BulkActionResponse)
async def bulk_analyze_clips(
    payload: BulkClipIds,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> BulkActionResponse:
    clips = (
        (
            await session.execute(
                select(Clip).join(Camera).where(Clip.id.in_(payload.clip_ids), Camera.enabled)
            )
        )
        .scalars()
        .all()
    )
    queued = 0
    failed = 0
    for clip in clips:
        if clip.storage_path:
            await request.app.state.arq_redis.enqueue_job(ANALYZE_JOB_NAME, clip_id=str(clip.id))
            queued += 1
        else:
            failed += 1
    failed += len(payload.clip_ids) - len(clips)  # not downloaded, or camera disabled
    return BulkActionResponse(succeeded=queued, failed=failed)


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


def _sanitize_path_segment(value: str) -> str:
    """A camera name or filename is free text - never let it inject extra
    path segments into the archive."""
    return value.replace("/", "-").replace("\\", "-")


def _clip_arcname(camera_name: str, clip: Clip) -> str:
    date_folder = f"{clip.recorded_at:%Y-%m-%d}"
    filename = _sanitize_path_segment(clip.filename or f"{clip.id}.mp4")
    return f"{_sanitize_path_segment(camera_name)}/{date_folder}/{filename}"


def _build_zip(
    local_entries: list[tuple[Path, str]], remote_entries: list[tuple[str, bytes]]
) -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)  # noqa: SIM115
    tmp.close()
    tmp_path = Path(tmp.name)
    with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_STORED) as zf:
        for path, arcname in local_entries:
            if path.exists():
                zf.write(path, arcname=arcname)
        for arcname, data in remote_entries:
            zf.writestr(arcname, data)
    return tmp_path


async def _cloud_client_for(
    session: AsyncSession, backend: StorageBackend, encryption_key: str
) -> CloudClient | None:
    row = await get_storage_integration_settings(session)
    if backend == StorageBackend.S3:
        return build_s3_client(row, encryption_key)
    if backend == StorageBackend.GOOGLE_DRIVE:
        return build_google_drive_client(row, encryption_key)
    return build_onedrive_client(row, encryption_key)


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

    camera_ids = {c.camera_id for c in downloadable}
    cameras = (
        (await session.execute(select(Camera).where(Camera.id.in_(camera_ids)))).scalars().all()
    )
    camera_names = {c.id: c.name for c in cameras}

    storage_root = await resolve_storage_dir(session, get_settings())
    local_storage = get_clip_storage(storage_root)
    encryption_key = get_settings().encryption_key
    clients: dict[StorageBackend, CloudClient | None] = {}

    local_entries: list[tuple[Path, str]] = []
    remote_entries: list[tuple[str, bytes]] = []
    for clip in downloadable:
        camera_name = camera_names.get(clip.camera_id, "Unknown Camera")
        arcname = _clip_arcname(camera_name, clip)
        if clip.storage_backend == StorageBackend.LOCAL:
            local_entries.append((local_storage.clip_path(clip.camera_id, clip.id), arcname))
            continue
        if clip.storage_backend not in clients:
            clients[clip.storage_backend] = await _cloud_client_for(
                session, clip.storage_backend, encryption_key
            )
        client = clients[clip.storage_backend]
        if client is None:
            continue
        try:
            data = await client.download(clip.storage_path)  # type: ignore[arg-type]
        except CloudStorageError as exc:
            logger.warning(
                "clips.bulk_download_remote_fetch_failed", clip_id=str(clip.id), error=str(exc)
            )
            continue
        remote_entries.append((arcname, data))

    if not local_entries and not remote_entries:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="None of the selected clips could be read.",
        )

    zip_path = await asyncio.to_thread(_build_zip, local_entries, remote_entries)
    zip_name = f"clips-{datetime.now(UTC):%Y%m%d-%H%M%S}.zip"
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=zip_name,
        background=BackgroundTask(zip_path.unlink, missing_ok=True),
    )
