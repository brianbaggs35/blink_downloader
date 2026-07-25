"""Camera listing and per-camera enable/disable."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.blink.models import Camera
from app.blink.schemas import CameraRead, CameraUpdate
from app.db import get_session
from app.users.auth import current_active_user, current_superuser

router = APIRouter(prefix="/cameras", tags=["cameras"])


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
    camera = await session.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found.")
    camera.enabled = payload.enabled
    await session.commit()
    await session.refresh(camera)
    return camera
