"""Pydantic schemas for the Blink account/camera API surface."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.blink.models import BlinkAccountStatus


class BlinkLinkRequest(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=255)


class BlinkVerifyRequest(BaseModel):
    link_session_id: uuid.UUID
    code: str = Field(min_length=1, max_length=20)


class BlinkLinkResponse(BaseModel):
    status: Literal["linked", "verification_required"]
    link_session_id: uuid.UUID | None = None


class BlinkStatusResponse(BaseModel):
    linked: bool
    status: BlinkAccountStatus | None = None
    last_sync: datetime | None = None
    last_error: str | None = None
    camera_count: int = 0


class CameraRead(BaseModel):
    id: uuid.UUID
    name: str
    camera_type: str
    enabled: bool
    battery: str | None
    last_synced_at: datetime | None
    security_context: str | None

    model_config = {"from_attributes": True}


class CameraUpdate(BaseModel):
    enabled: bool
    security_context: str | None = Field(default=None, max_length=2000)


class ClipRead(BaseModel):
    id: uuid.UUID
    camera_id: uuid.UUID
    recorded_at: datetime
    duration_seconds: float | None
    file_size_bytes: int | None
    downloaded_at: datetime | None
    deleted_on_blink: bool
    thumbnail_generated: bool

    model_config = {"from_attributes": True}


class ClipListResponse(BaseModel):
    items: list[ClipRead]
    total: int
    page: int
    page_size: int


class BulkClipIds(BaseModel):
    clip_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


class BulkActionResponse(BaseModel):
    succeeded: int
    failed: int
