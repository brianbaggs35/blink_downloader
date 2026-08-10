"""Cloud storage integration settings: one household, one set of providers.

S3 access keys and Google Drive/OneDrive OAuth client secrets/refresh
tokens are encrypted at rest (:mod:`app.security.crypto`), same convention
as :class:`app.alerts.models.AlertSettings`.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.blink.models import StorageBackend
from app.db import Base
from app.db import str_enum as _str_enum

SINGLETON_ID = uuid.UUID("00000000-0000-0000-0000-000000000003")


class StorageIntegrationSettings(Base):
    __tablename__ = "storage_integration_settings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)

    s3_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    s3_bucket: Mapped[str | None] = mapped_column(Text)
    s3_region: Mapped[str | None] = mapped_column(Text)
    # Optional key prefix so a shared bucket can keep clips under e.g.
    # "blink-clips/" instead of at the bucket root.
    s3_prefix: Mapped[str | None] = mapped_column(Text)
    encrypted_s3_access_key_id: Mapped[str | None] = mapped_column(Text)
    encrypted_s3_secret_access_key: Mapped[str | None] = mapped_column(Text)

    google_drive_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    # The client id/secret identify *our app* (registered by the admin in
    # Google Cloud Console) - not a secret on their own, but kept alongside
    # the encrypted fields since they're only ever used together.
    google_drive_client_id: Mapped[str | None] = mapped_column(Text)
    encrypted_google_drive_client_secret: Mapped[str | None] = mapped_column(Text)
    # Set once, after the OAuth consent flow completes; a long-lived
    # refresh token is what makes uploads/downloads work without the admin
    # re-authenticating every hour.
    encrypted_google_drive_refresh_token: Mapped[str | None] = mapped_column(Text)
    google_drive_folder_id: Mapped[str | None] = mapped_column(Text)

    onedrive_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    onedrive_client_id: Mapped[str | None] = mapped_column(Text)
    encrypted_onedrive_client_secret: Mapped[str | None] = mapped_column(Text)
    encrypted_onedrive_refresh_token: Mapped[str | None] = mapped_column(Text)
    onedrive_folder_path: Mapped[str | None] = mapped_column(Text)

    # Where a newly-downloaded clip should end up living. LOCAL (the
    # default) preserves today's behavior; any other value makes
    # app.worker.tasks.analyze upload-then-delete-local right after a
    # clip finishes analysis (or, if auto-analysis is off, right after
    # download) - see app.integrations.archive.archive_clip.
    auto_archive_backend: Mapped[StorageBackend] = mapped_column(
        _str_enum(StorageBackend, "storage_auto_archive_backend", length=20),
        default=StorageBackend.LOCAL,
        server_default=StorageBackend.LOCAL.name,
    )
    # 0 (the default) preserves today's behavior: archive immediately once a
    # clip is done with local disk. A positive value defers the archive job
    # by that many days instead, so a clip stays browsable locally for a
    # while before moving off to auto_archive_backend.
    auto_archive_after_days: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    # CSRF state for whichever OAuth flow (if any) is currently in progress -
    # a single household admin only ever has one flow in flight at a time,
    # so this lives on the singleton row rather than a separate table.
    pending_oauth_provider: Mapped[str | None] = mapped_column(Text)
    pending_oauth_state: Mapped[str | None] = mapped_column(Text)
    # PKCE verifier for the in-flight flow (Google Drive only - OneDrive's
    # msal-based flow doesn't use PKCE). Same plain-text treatment as
    # pending_oauth_state: equally short-lived/single-use CSRF-adjacent
    # flow state, not a long-lived secret like a refresh token.
    pending_oauth_code_verifier: Mapped[str | None] = mapped_column(Text)
    pending_oauth_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
