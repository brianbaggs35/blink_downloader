"""Camera listing, per-camera enable/disable, and live preview/record."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.blink.models import Camera
from app.blink.schemas import CameraRead, CameraUpdate
from app.blink.service import BlinkAuthError, BlinkError
from app.config import get_settings
from app.db import get_session
from app.livefeed.service import get_camera_preview, record_camera_clip
from app.logs import get_logger
from app.settings.service import resolve_storage_dir
from app.storage.service import get_clip_storage
from app.users.auth import current_active_user, current_superuser
from app.users.models import User

logger = get_logger(__name__)

router = APIRouter(prefix="/cameras", tags=["cameras"])


async def _get_camera_or_404(session: AsyncSession, camera_id: uuid.UUID) -> Camera:
    camera = await session.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found.")
    return camera


@router.get("", response_model=list[CameraRead])
async def list_cameras(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_active_user)],
) -> list[Camera]:
    result = await session.execute(select(Camera).order_by(Camera.name))
    return list(result.scalars().all())


@router.patch("/{camera_id}", response_model=CameraRead)
async def update_camera(
    camera_id: uuid.UUID,
    payload: CameraUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> Camera:
    camera = await _get_camera_or_404(session, camera_id)
    camera.enabled = payload.enabled
    camera.security_context = payload.security_context
    await session.commit()
    await session.refresh(camera)
    return camera


@router.get("/{camera_id}/preview")
async def get_preview(
    camera_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(current_active_user)],
    force: bool = False,
) -> FileResponse:
    camera = await _get_camera_or_404(session, camera_id)
    if force and not user.is_superuser:
        # A forced snap wakes a battery-powered camera on demand - same
        # "costs something real" bar as export/delete elsewhere in the API.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an administrator can force a fresh snapshot.",
        )
    settings = get_settings()
    storage = get_clip_storage(await resolve_storage_dir(session, settings))
    try:
        path = await get_camera_preview(session, settings, camera, storage, force=force)
    except BlinkAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Blink session needs re-linking: {exc}",
        ) from exc
    except BlinkError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    # Cache-Control: no-store is already applied to every response by
    # SecurityHeadersMiddleware - adding it again here would just duplicate it.
    # get_camera_preview() always sets preview_updated_at on success; "now" is
    # just a harmless type-safe fallback for this purely informational header.
    updated_at = camera.preview_updated_at or datetime.now(UTC)
    headers = {"X-Preview-Updated-At": updated_at.isoformat()}
    return FileResponse(
        path, media_type="image/jpeg", content_disposition_type="inline", headers=headers
    )


@router.post("/{camera_id}/record", status_code=status.HTTP_202_ACCEPTED)
async def record_clip(
    camera_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> dict[str, str]:
    camera = await _get_camera_or_404(session, camera_id)
    settings = get_settings()
    try:
        await record_camera_clip(session, settings, camera)
    except BlinkAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Blink session needs re-linking: {exc}",
        ) from exc
    except BlinkError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    logger.info("livefeed.clip_recording_triggered", camera_id=str(camera_id))
    return {"status": "recording_started"}
