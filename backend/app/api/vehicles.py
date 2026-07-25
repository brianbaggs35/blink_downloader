"""Vehicle protection: outline, thresholds, and proximity history.

Configuration (capture a reference frame, draw/edit the outline, set
thresholds) is admin-only; viewing the current setup and proximity history
is available to any signed-in household member, matching the rest of the
AI/clips surface.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.blink.models import Camera
from app.config import get_settings
from app.db import get_session
from app.settings.service import resolve_storage_dir
from app.storage.service import ClipStorage, get_clip_storage
from app.users.auth import current_active_user, current_superuser
from app.vehicles.models import ProximityEvent, Vehicle
from app.vehicles.schemas import ProximityEventRead, VehicleRead, VehicleUpdate
from app.vehicles.service import (
    VehicleReferenceFrameError,
    capture_vehicle_reference_frame,
    delete_vehicle,
    get_vehicle,
    upsert_vehicle,
)

router = APIRouter(prefix="/vehicles", tags=["vehicles"])


async def _storage(session: AsyncSession) -> ClipStorage:
    return get_clip_storage(await resolve_storage_dir(session, get_settings()))


def _vehicle_read(vehicle: Vehicle, camera_name: str, storage: ClipStorage) -> VehicleRead:
    return VehicleRead(
        id=vehicle.id,
        camera_id=vehicle.camera_id,
        camera_name=camera_name,
        description=vehicle.description,
        outline_points=vehicle.outline_points,
        has_reference_frame=storage.vehicle_reference_path(vehicle.camera_id).exists(),
        estimated_length_feet=vehicle.estimated_length_feet,
        distance_threshold_feet=vehicle.distance_threshold_feet,
        enabled=vehicle.enabled,
        updated_at=vehicle.updated_at,
    )


async def _get_camera_or_404(session: AsyncSession, camera_id: uuid.UUID) -> Camera:
    camera = await session.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found.")
    return camera


async def _get_vehicle_or_404(session: AsyncSession, camera_id: uuid.UUID) -> Vehicle:
    vehicle = await get_vehicle(session, camera_id)
    if vehicle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No vehicle registered for this camera."
        )
    return vehicle


@router.get("", response_model=list[VehicleRead])
async def list_vehicles(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_active_user)],
) -> list[VehicleRead]:
    storage = await _storage(session)
    stmt = select(Vehicle, Camera.name).join(Camera, Vehicle.camera_id == Camera.id)
    rows = (await session.execute(stmt)).all()
    return [_vehicle_read(vehicle, camera_name, storage) for vehicle, camera_name in rows]


@router.get("/{camera_id}", response_model=VehicleRead)
async def get_vehicle_for_camera(
    camera_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_active_user)],
) -> VehicleRead:
    camera = await _get_camera_or_404(session, camera_id)
    vehicle = await _get_vehicle_or_404(session, camera_id)
    return _vehicle_read(vehicle, camera.name, await _storage(session))


@router.put("/{camera_id}", response_model=VehicleRead)
async def put_vehicle(
    camera_id: uuid.UUID,
    payload: VehicleUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> VehicleRead:
    camera = await _get_camera_or_404(session, camera_id)
    vehicle = await upsert_vehicle(session, camera_id, payload)
    return _vehicle_read(vehicle, camera.name, await _storage(session))


@router.delete("/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_vehicle(
    camera_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> None:
    vehicle = await _get_vehicle_or_404(session, camera_id)
    await delete_vehicle(session, vehicle, await _storage(session))


@router.post("/{camera_id}/reference-frame", status_code=status.HTTP_204_NO_CONTENT)
async def capture_reference(
    camera_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> None:
    await _get_camera_or_404(session, camera_id)
    try:
        await capture_vehicle_reference_frame(session, camera_id, await _storage(session))
    except VehicleReferenceFrameError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/{camera_id}/reference-frame")
async def get_reference_frame(
    camera_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_active_user)],
) -> FileResponse:
    path = (await _storage(session)).vehicle_reference_path(camera_id)
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No reference frame captured yet."
        )
    return FileResponse(path, media_type="image/jpeg", content_disposition_type="inline")


@router.get("/{camera_id}/proximity-events", response_model=list[ProximityEventRead])
async def list_proximity_events(
    camera_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_active_user)],
) -> list[ProximityEvent]:
    vehicle = await _get_vehicle_or_404(session, camera_id)
    stmt = (
        select(ProximityEvent)
        .where(ProximityEvent.vehicle_id == vehicle.id)
        .order_by(ProximityEvent.occurred_at.desc())
        .limit(50)
    )
    return list((await session.execute(stmt)).scalars().all())
