"""Pydantic schemas for admin-editable runtime settings."""

from pathlib import Path

from pydantic import BaseModel, Field, field_validator


class StorageSettingsRead(BaseModel):
    storage_dir: str
    is_default: bool
    """True when no override is set and this reflects BLINK_STORAGE_DIR."""
    local_storage_quota_bytes: int | None
    """An admin-set budget for local disk usage, or null for unlimited -
    informational only (see get_storage_summary), never enforced."""


class StorageSettingsUpdate(BaseModel):
    storage_dir: str | None = None
    """An absolute path, or null to fall back to BLINK_STORAGE_DIR."""
    local_storage_quota_bytes: int | None = Field(default=None, gt=0)

    @field_validator("storage_dir")
    @classmethod
    def _must_be_absolute(cls, value: str | None) -> str | None:
        if value is not None and not Path(value).is_absolute():
            msg = "storage_dir must be an absolute path."
            raise ValueError(msg)
        return value


class StorageBrowseEntry(BaseModel):
    name: str
    path: str


class StorageBrowseResponse(BaseModel):
    path: str
    parent_path: str | None
    """None when `path` is the filesystem root."""
    directories: list[StorageBrowseEntry]


class StorageCreateFolderRequest(BaseModel):
    parent_path: str
    name: str = Field(min_length=1, max_length=255)

    @field_validator("parent_path")
    @classmethod
    def _parent_must_be_absolute(cls, value: str) -> str:
        if not Path(value).is_absolute():
            msg = "parent_path must be an absolute path."
            raise ValueError(msg)
        return value

    @field_validator("name")
    @classmethod
    def _name_has_no_path_separators(cls, value: str) -> str:
        if "/" in value or "\\" in value or value in {".", ".."}:
            msg = "name must be a plain folder name, not a path."
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
