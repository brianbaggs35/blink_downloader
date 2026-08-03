"""Camera listing, per-camera enable/disable, live preview/record, and
real Live View streaming."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.blink.models import Camera
from app.blink.schemas import CameraRead, CameraUpdate
from app.blink.service import BlinkAuthError, BlinkError, LiveViewUnsupportedError
from app.config import get_settings
from app.db import get_session
from app.livefeed.live_stream import PLAYLIST_FILENAME, LiveViewSessionManager, LiveViewStartError
from app.livefeed.schemas import LiveViewSessionRead
from app.livefeed.service import get_camera_preview, record_camera_clip, start_live_view
from app.logs import get_logger
from app.settings.service import resolve_storage_dir
from app.storage.service import get_clip_storage
from app.users.auth import current_active_user, current_superuser
from app.users.models import User

logger = get_logger(__name__)

router = APIRouter(prefix="/cameras", tags=["cameras"])


def _live_view_manager(request: Request) -> LiveViewSessionManager:
    return request.app.state.live_view_manager


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


# ------------------------------------------------------------------ live view


@router.post(
    "/{camera_id}/live-view/start",
    response_model=LiveViewSessionRead,
    status_code=status.HTTP_201_CREATED,
)
async def start_live_view_route(
    camera_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    manager: Annotated[LiveViewSessionManager, Depends(_live_view_manager)],
    _user: Annotated[object, Depends(current_superuser)],
) -> LiveViewSessionRead:
    camera = await _get_camera_or_404(session, camera_id)
    settings = get_settings()
    try:
        live_session = await start_live_view(session, settings, camera, manager)
    except BlinkAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Blink session needs re-linking: {exc}",
        ) from exc
    except LiveViewUnsupportedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (BlinkError, LiveViewStartError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    logger.info(
        "live_view.started", camera_id=str(camera_id), session_id=str(live_session.session_id)
    )
    return LiveViewSessionRead(
        session_id=live_session.session_id,
        camera_id=camera_id,
        playlist_url=(
            f"/api/cameras/{camera_id}/live-view/{live_session.session_id}/{PLAYLIST_FILENAME}"
        ),
    )


@router.post(
    "/{camera_id}/live-view/{live_session_id}/stop", status_code=status.HTTP_204_NO_CONTENT
)
async def stop_live_view_route(
    camera_id: uuid.UUID,
    live_session_id: uuid.UUID,
    manager: Annotated[LiveViewSessionManager, Depends(_live_view_manager)],
    _user: Annotated[object, Depends(current_superuser)],
) -> None:
    live_session = manager.get(live_session_id)
    if live_session is not None and live_session.camera_id == camera_id:
        await manager.stop_session(live_session_id)
    logger.info("live_view.stopped", camera_id=str(camera_id), session_id=str(live_session_id))


@router.get("/{camera_id}/live-view/{live_session_id}/{filename}")
async def get_live_view_file(
    camera_id: uuid.UUID,
    live_session_id: uuid.UUID,
    filename: str,
    manager: Annotated[LiveViewSessionManager, Depends(_live_view_manager)],
    _user: Annotated[User, Depends(current_active_user)],
) -> FileResponse:
    live_session = manager.get(live_session_id)
    if live_session is None or live_session.camera_id != camera_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This live view session has ended or was never started.",
        )
    path = manager.get_file(live_session_id, filename)
    if path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found.")
    # Cache-Control: no-store is already applied to every response by
    # SecurityHeadersMiddleware - adding it again here would just duplicate
    # it (see get_preview above).
    media_type = "application/vnd.apple.mpegurl" if filename.endswith(".m3u8") else "video/mp2t"
    return FileResponse(path, media_type=media_type)
