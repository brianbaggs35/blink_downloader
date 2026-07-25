"""Vehicle CRUD and reference-frame capture.

Capturing a reference frame and drawing/saving an outline are separate
steps (a household member captures a frame, then traces over it, then
saves) — a reference frame is stored per-camera independent of whether a
Vehicle row exists yet, so the capture step never requires a complete
outline first.
"""

import asyncio
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.blink.models import Clip
from app.storage.service import ClipStorage
from app.vehicles.models import Vehicle
from app.vehicles.schemas import VehicleUpdate
from app.video.ffmpeg import capture_reference_frame


class VehicleReferenceFrameError(Exception):
    """No downloaded clip to capture a reference frame from, or ffmpeg
    couldn't extract one from the clip that exists."""


async def get_vehicle(session: AsyncSession, camera_id: uuid.UUID) -> Vehicle | None:
    return (
        await session.execute(select(Vehicle).where(Vehicle.camera_id == camera_id))
    ).scalar_one_or_none()


async def upsert_vehicle(
    session: AsyncSession, camera_id: uuid.UUID, payload: VehicleUpdate
) -> Vehicle:
    vehicle = await get_vehicle(session, camera_id)
    if vehicle is None:
        vehicle = Vehicle(camera_id=camera_id, description=payload.description)
        session.add(vehicle)
    vehicle.description = payload.description
    vehicle.outline_points = [list(p) for p in payload.outline_points]
    vehicle.estimated_length_feet = payload.estimated_length_feet
    vehicle.distance_threshold_feet = payload.distance_threshold_feet
    vehicle.enabled = payload.enabled
    await session.commit()
    await session.refresh(vehicle)
    return vehicle


async def delete_vehicle(session: AsyncSession, vehicle: Vehicle, storage: ClipStorage) -> None:
    await storage.delete(storage.vehicle_reference_path(vehicle.camera_id))
    await session.delete(vehicle)
    await session.commit()


async def capture_vehicle_reference_frame(
    session: AsyncSession, camera_id: uuid.UUID, storage: ClipStorage
) -> Path:
    stmt = (
        select(Clip)
        .where(Clip.camera_id == camera_id, Clip.storage_path.is_not(None))
        .order_by(Clip.recorded_at.desc())
        .limit(1)
    )
    clip = (await session.execute(stmt)).scalar_one_or_none()
    if clip is None or not clip.storage_path:
        raise VehicleReferenceFrameError("No downloaded clips yet for this camera.")

    destination = storage.vehicle_reference_path(camera_id)
    await asyncio.to_thread(destination.parent.mkdir, parents=True, exist_ok=True)
    ok = await capture_reference_frame(Path(clip.storage_path), destination)
    if not ok:
        raise VehicleReferenceFrameError("Could not capture a reference frame from that clip.")
    return destination
