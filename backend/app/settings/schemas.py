"""Pydantic schemas for admin-editable runtime settings."""

from pathlib import Path

from pydantic import BaseModel, field_validator


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
