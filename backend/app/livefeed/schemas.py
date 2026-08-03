"""Pydantic schemas for the Live View and Security Feed settings API."""

import uuid

from pydantic import BaseModel, Field


class LiveViewSettingsRead(BaseModel):
    default_camera_id: uuid.UUID | None
    auto_refresh_enabled: bool
    auto_refresh_interval_seconds: int


class LiveViewSettingsUpdate(BaseModel):
    default_camera_id: uuid.UUID | None = None
    auto_refresh_enabled: bool = False
    auto_refresh_interval_seconds: int = Field(default=10, ge=3, le=120)


class SecurityFeedSettingsRead(BaseModel):
    camera_ids: list[uuid.UUID]
    columns: int
    refresh_interval_seconds: int


class SecurityFeedSettingsUpdate(BaseModel):
    camera_ids: list[uuid.UUID] = Field(default_factory=list[uuid.UUID], max_length=24)
    columns: int = Field(default=2, ge=1, le=4)
    refresh_interval_seconds: int = Field(default=20, ge=5, le=300)


class LiveViewSessionRead(BaseModel):
    session_id: uuid.UUID
    camera_id: uuid.UUID
    playlist_url: str
