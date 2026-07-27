"""Pydantic schemas for admin-editable runtime settings."""

from pathlib import Path

from pydantic import BaseModel, Field, field_validator


class StorageSettingsRead(BaseModel):
    storage_dir: str
    is_default: bool
    """True when no override is set and this reflects BLINK_STORAGE_DIR."""


class StorageSettingsUpdate(BaseModel):
    storage_dir: str | None = None
    """An absolute path, or null to fall back to BLINK_STORAGE_DIR."""

    @field_validator("storage_dir")
    @classmethod
    def _must_be_absolute(cls, value: str | None) -> str | None:
        if value is not None and not Path(value).is_absolute():
            msg = "storage_dir must be an absolute path."
            raise ValueError(msg)
        return value


class BlinkSyncSettingsRead(BaseModel):
    sync_interval_seconds: int
    initial_sync_days: int
    auto_analyze_limit: int
    is_default: bool
    """True when none of the three are overridden and all reflect env defaults."""


class BlinkSyncSettingsUpdate(BaseModel):
    sync_interval_seconds: int | None = Field(default=None, ge=10, le=3600)
    initial_sync_days: int | None = Field(default=None, ge=1, le=30)
    auto_analyze_limit: int | None = Field(default=None, ge=1, le=20)
    """Each null falls back to its BLINK_-prefixed env var default."""
