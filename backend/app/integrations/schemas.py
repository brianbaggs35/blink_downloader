"""Pydantic schemas for the Storage Integrations settings API and the
Storage tab's archive/restore/summary endpoints."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.blink.models import StorageBackend


class StorageIntegrationSettingsRead(BaseModel):
    s3_enabled: bool
    s3_bucket: str | None
    s3_region: str | None
    s3_prefix: str | None
    s3_credentials_set: bool

    google_drive_enabled: bool
    google_drive_client_id: str | None
    google_drive_client_secret_set: bool
    google_drive_connected: bool
    """True once the OAuth consent flow has completed and a refresh token
    is stored - independent of google_drive_enabled, which just gates
    whether archiving actually offers this provider."""
    google_drive_folder_id: str | None

    onedrive_enabled: bool
    onedrive_client_id: str | None
    onedrive_client_secret_set: bool
    onedrive_connected: bool
    onedrive_folder_path: str | None

    auto_archive_backend: StorageBackend
    """Where a newly-downloaded clip ends up living. LOCAL (the default)
    keeps today's behavior; any other value uploads-then-deletes-local
    right after the clip finishes analysis."""


class StorageIntegrationSettingsUpdate(BaseModel):
    s3_enabled: bool = False
    s3_bucket: str | None = None
    s3_region: str | None = None
    s3_prefix: str | None = None
    s3_access_key_id: str | None = None
    """None leaves the stored key untouched; "" clears it."""
    s3_secret_access_key: str | None = None

    google_drive_enabled: bool = False
    google_drive_client_id: str | None = None
    google_drive_client_secret: str | None = None
    google_drive_folder_id: str | None = None

    onedrive_enabled: bool = False
    onedrive_client_id: str | None = None
    onedrive_client_secret: str | None = None
    onedrive_folder_path: str | None = None

    auto_archive_backend: StorageBackend = StorageBackend.LOCAL


class StorageTestResult(BaseModel):
    ok: bool
    detail: str


class StorageTestResponse(BaseModel):
    s3: StorageTestResult | None = None
    google_drive: StorageTestResult | None = None
    onedrive: StorageTestResult | None = None


class BackendStorageSummary(BaseModel):
    backend: StorageBackend
    clip_count: int
    total_bytes: int


class StorageSummaryResponse(BaseModel):
    by_backend: list[BackendStorageSummary]
    total_clips: int
    total_bytes: int


class ArchiveClipsRequest(BaseModel):
    clip_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    backend: StorageBackend


class RestoreClipsRequest(BaseModel):
    clip_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)


class TemporaryLinkResponse(BaseModel):
    url: str
    expires_at: datetime
