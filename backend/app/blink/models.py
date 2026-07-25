"""Blink account, camera, and clip tables.

Credentials and tokens are stored encrypted (see :mod:`app.security.crypto`);
nothing here ever holds plaintext.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.db import str_enum as _str_enum


class BlinkAccountStatus(StrEnum):
    PENDING_2FA = "pending_2fa"
    ACTIVE = "active"
    ERROR = "error"


class StorageBackend(StrEnum):
    LOCAL = "local"


class BlinkAccount(Base):
    __tablename__ = "blink_accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    encrypted_username: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_password: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_token_data: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[BlinkAccountStatus] = mapped_column(
        _str_enum(BlinkAccountStatus, "blink_account_status", length=20),
        default=BlinkAccountStatus.ACTIVE,
        server_default=BlinkAccountStatus.ACTIVE.value,
    )
    last_sync: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    cameras: Mapped[list[Camera]] = relationship(
        back_populates="blink_account", cascade="all, delete-orphan"
    )


class Camera(Base):
    __tablename__ = "cameras"
    __table_args__ = (
        UniqueConstraint("blink_account_id", "blink_camera_id", name="uq_cameras_blink_camera"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    blink_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("blink_accounts.id", ondelete="cascade"),
        nullable=False,
        index=True,
    )
    blink_camera_id: Mapped[str] = mapped_column(Text, nullable=False)
    blink_network_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    camera_type: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True, server_default="true")
    battery: Mapped[str | None] = mapped_column(Text)
    thumbnail_path: Mapped[str | None] = mapped_column(Text)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Free-text context the AI prompt is given verbatim, e.g. "watches the
    # driveway and front walkway" — never guessed, always admin-authored.
    security_context: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    blink_account: Mapped[BlinkAccount] = relationship(back_populates="cameras")
    clips: Mapped[list[Clip]] = relationship(back_populates="camera", cascade="all, delete-orphan")


class Clip(Base):
    __tablename__ = "clips"
    __table_args__ = (
        UniqueConstraint("camera_id", "blink_clip_id", name="uq_clips_blink_clip"),
        Index("ix_clips_camera_id", "camera_id"),
        Index("ix_clips_recorded_at", "recorded_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    camera_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cameras.id", ondelete="cascade"), nullable=False
    )
    blink_clip_id: Mapped[str] = mapped_column(Text, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deleted_on_blink: Mapped[bool] = mapped_column(default=False, server_default="false")

    storage_backend: Mapped[StorageBackend] = mapped_column(
        _str_enum(StorageBackend, "clip_storage_backend", length=20),
        default=StorageBackend.LOCAL,
        server_default=StorageBackend.LOCAL.value,
    )
    storage_path: Mapped[str | None] = mapped_column(Text)
    filename: Mapped[str | None] = mapped_column(Text)
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    file_size_bytes: Mapped[int | None] = mapped_column()
    duration_seconds: Mapped[float | None] = mapped_column()
    thumbnail_generated: Mapped[bool] = mapped_column(default=False, server_default="false")

    raw_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    camera: Mapped[Camera] = relationship(back_populates="clips")
