"""Sync Module control: arm/disarm, per-camera motion detection, and local
(USB) storage browsing/download/delete.

Viewing is available to any signed-in household member (matching Vehicles/
Biometrics); every mutation - arming, motion toggling, and local-storage
download/delete - is admin-only, matching every other "changes real device
state" action already in this app (recording a clip, forcing a snapshot,
enabling/disabling a camera).
"""

import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.blink.models import Camera
from app.blink.schemas import BulkActionResponse
from app.blink.service import BlinkError
from app.config import get_settings
from app.db import get_session
from app.logs import get_logger
from app.sync_module.models import SyncModule, SyncModuleLocalItem
from app.sync_module.schemas import (
    MotionDetectionUpdate,
    SyncModuleArmRequest,
    SyncModuleCameraRead,
    SyncModuleLocalItemRead,
    SyncModuleRead,
)
from app.sync_module.service import (
    MotionNotSupportedError,
    arm_sync_module,
    bulk_set_camera_motion_detection,
    list_cameras_for_sync_module,
    list_local_items,
    list_sync_modules,
    set_camera_motion_detection,
)
from app.users.auth import current_active_user, current_superuser
from app.worker.tasks.sync_module import (
    DELETE_LOCAL_ITEM_JOB_NAME,
    DOWNLOAD_LOCAL_ITEM_JOB_NAME,
    REFRESH_LOCAL_STORAGE_JOB_NAME,
)

router = APIRouter(prefix="/sync-modules", tags=["sync-modules"])
logger = get_logger(__name__)


def _sync_module_read(sync_module: SyncModule, camera_count: int) -> SyncModuleRead:
    return SyncModuleRead(
        id=sync_module.id,
        network_id=sync_module.network_id,
        name=sync_module.name,
        serial=sync_module.serial,
        firmware_version=sync_module.firmware_version,
        is_physical_hub=sync_module.is_physical_hub,
        armed=sync_module.armed,
        online=sync_module.online,
        local_storage_compatible=sync_module.local_storage_compatible,
        local_storage_enabled=sync_module.local_storage_enabled,
        local_storage_active=sync_module.local_storage_active,
        local_storage_status=sync_module.local_storage_status,
        local_storage_manifest_refreshed_at=sync_module.local_storage_manifest_refreshed_at,
        local_storage_last_error=sync_module.local_storage_last_error,
        camera_count=camera_count,
        last_synced_at=sync_module.last_synced_at,
    )


def _camera_read(camera: Camera) -> SyncModuleCameraRead:
    return SyncModuleCameraRead(
        camera_id=camera.id,
        name=camera.name,
        camera_type=camera.camera_type,
        motion_enabled=camera.motion_enabled,
        motion_supported=camera.motion_action_type != "mini",
        battery=camera.battery,
    )


def _local_item_read(item: SyncModuleLocalItem) -> SyncModuleLocalItemRead:
    return SyncModuleLocalItemRead(
        id=item.id,
        camera_id=item.camera_id,
        camera_name=item.camera_name,
        recorded_at=item.recorded_at,
        size_bytes=item.size_bytes,
        present_on_device=item.present_on_device,
        status=item.status,
        downloaded_at=item.downloaded_at,
        last_error=item.last_error,
    )


async def _get_sync_module_or_404(session: AsyncSession, sync_module_id: uuid.UUID) -> SyncModule:
    sync_module = await session.get(SyncModule, sync_module_id)
    if sync_module is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sync module not found.")
    return sync_module


async def _get_camera_or_404(
    session: AsyncSession, sync_module: SyncModule, camera_id: uuid.UUID
) -> Camera:
    for camera in await list_cameras_for_sync_module(session, sync_module):
        if camera.id == camera_id:
            return camera
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found.")


def _local_item_file_or_404(storage_path: str | None) -> Path:
    if storage_path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="This clip hasn't been downloaded yet."
        )
    path = Path(storage_path)
    if not path.exists():
        logger.error("sync_modules.file_missing_on_disk", path=storage_path)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This clip's file is missing from storage.",
        )
    return path


async def _get_local_item_or_404(
    session: AsyncSession, sync_module: SyncModule, item_id: uuid.UUID
) -> SyncModuleLocalItem:
    for item in await list_local_items(session, sync_module):
        if item.id == item_id:
            return item
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="Local storage item not found."
    )


@router.get("", response_model=list[SyncModuleRead])
async def list_sync_modules_route(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_active_user)],
) -> list[SyncModuleRead]:
    result: list[SyncModuleRead] = []
    for sync_module in await list_sync_modules(session):
        cameras = await list_cameras_for_sync_module(session, sync_module)
        result.append(_sync_module_read(sync_module, len(cameras)))
    return result


@router.get("/{sync_module_id}/cameras", response_model=list[SyncModuleCameraRead])
async def list_sync_module_cameras_route(
    sync_module_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_active_user)],
) -> list[SyncModuleCameraRead]:
    sync_module = await _get_sync_module_or_404(session, sync_module_id)
    cameras = await list_cameras_for_sync_module(session, sync_module)
    return [_camera_read(camera) for camera in cameras]


@router.post("/{sync_module_id}/arm", response_model=SyncModuleRead)
async def arm_sync_module_route(
    sync_module_id: uuid.UUID,
    payload: SyncModuleArmRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> SyncModuleRead:
    sync_module = await _get_sync_module_or_404(session, sync_module_id)
    try:
        sync_module = await arm_sync_module(session, get_settings(), sync_module, payload.armed)
    except BlinkError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    cameras = await list_cameras_for_sync_module(session, sync_module)
    return _sync_module_read(sync_module, len(cameras))


@router.patch("/{sync_module_id}/cameras/{camera_id}/motion", response_model=SyncModuleCameraRead)
async def set_camera_motion_detection_route(
    sync_module_id: uuid.UUID,
    camera_id: uuid.UUID,
    payload: MotionDetectionUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> SyncModuleCameraRead:
    sync_module = await _get_sync_module_or_404(session, sync_module_id)
    camera = await _get_camera_or_404(session, sync_module, camera_id)
    try:
        camera = await set_camera_motion_detection(
            session, get_settings(), camera, sync_module, payload.enabled
        )
    except MotionNotSupportedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except BlinkError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return _camera_read(camera)


@router.patch("/{sync_module_id}/cameras/motion", response_model=BulkActionResponse)
async def bulk_set_camera_motion_detection_route(
    sync_module_id: uuid.UUID,
    payload: MotionDetectionUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> BulkActionResponse:
    sync_module = await _get_sync_module_or_404(session, sync_module_id)
    cameras = await list_cameras_for_sync_module(session, sync_module)
    try:
        succeeded, failed = await bulk_set_camera_motion_detection(
            session, get_settings(), sync_module, cameras, payload.enabled
        )
    except BlinkError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return BulkActionResponse(succeeded=succeeded, failed=failed)


@router.get("/{sync_module_id}/local-storage/items", response_model=list[SyncModuleLocalItemRead])
async def list_local_storage_items_route(
    sync_module_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_active_user)],
) -> list[SyncModuleLocalItemRead]:
    sync_module = await _get_sync_module_or_404(session, sync_module_id)
    items = await list_local_items(session, sync_module)
    return [_local_item_read(item) for item in items]


@router.post("/{sync_module_id}/local-storage/refresh", status_code=status.HTTP_202_ACCEPTED)
async def refresh_local_storage_route(
    sync_module_id: uuid.UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> None:
    await _get_sync_module_or_404(session, sync_module_id)
    await request.app.state.arq_redis.enqueue_job(
        REFRESH_LOCAL_STORAGE_JOB_NAME, sync_module_id=str(sync_module_id)
    )


@router.post(
    "/{sync_module_id}/local-storage/items/{item_id}/download",
    status_code=status.HTTP_202_ACCEPTED,
)
async def download_local_storage_item_route(
    sync_module_id: uuid.UUID,
    item_id: uuid.UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> None:
    sync_module = await _get_sync_module_or_404(session, sync_module_id)
    await _get_local_item_or_404(session, sync_module, item_id)
    await request.app.state.arq_redis.enqueue_job(
        DOWNLOAD_LOCAL_ITEM_JOB_NAME, item_id=str(item_id)
    )


@router.delete(
    "/{sync_module_id}/local-storage/items/{item_id}", status_code=status.HTTP_202_ACCEPTED
)
async def delete_local_storage_item_route(
    sync_module_id: uuid.UUID,
    item_id: uuid.UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> None:
    sync_module = await _get_sync_module_or_404(session, sync_module_id)
    await _get_local_item_or_404(session, sync_module, item_id)
    await request.app.state.arq_redis.enqueue_job(DELETE_LOCAL_ITEM_JOB_NAME, item_id=str(item_id))


@router.get("/{sync_module_id}/local-storage/items/{item_id}/file")
async def get_local_storage_item_file_route(
    sync_module_id: uuid.UUID,
    item_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> FileResponse:
    sync_module = await _get_sync_module_or_404(session, sync_module_id)
    item = await _get_local_item_or_404(session, sync_module, item_id)
    path = _local_item_file_or_404(item.storage_path)
    return FileResponse(path, media_type="video/mp4", filename=f"{item.id}.mp4")
