"""Pydantic schemas for the Sync Module API surface."""

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.sync_module.models import LocalItemStatus, LocalStorageStatus


class SyncModuleRead(BaseModel):
    id: uuid.UUID
    network_id: str
    name: str
    serial: str | None
    firmware_version: str | None
    is_physical_hub: bool
    armed: bool | None
    online: bool
    local_storage_compatible: bool
    local_storage_enabled: bool
    local_storage_active: bool
    local_storage_status: LocalStorageStatus
    local_storage_manifest_refreshed_at: datetime | None
    local_storage_last_error: str | None
    camera_count: int
    last_synced_at: datetime | None


class SyncModuleArmRequest(BaseModel):
    armed: bool


class MotionDetectionUpdate(BaseModel):
    """Body for both the per-camera and the bulk "all cameras" motion
    detection routes - same shape, same field."""

    enabled: bool


class SyncModuleCameraRead(BaseModel):
    camera_id: uuid.UUID
    name: str
    camera_type: str
    motion_enabled: bool
    motion_supported: bool
    """False for a Mini camera - blinkpy's BlinkCameraMini.arm mirrors the
    Sync Module's own armed state rather than exposing an independent
    per-camera toggle."""
    battery: str | None


class SyncModuleLocalItemRead(BaseModel):
    id: uuid.UUID
    camera_id: uuid.UUID | None
    camera_name: str
    recorded_at: datetime
    size_bytes: int
    present_on_device: bool
    status: LocalItemStatus
    downloaded_at: datetime | None
    last_error: str | None
