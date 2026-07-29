"""A Blink network's Sync Module: arm state, online/firmware identity, and
(if it has a real physical hub with a USB drive attached) local storage
status and a cache of what's actually stored on that drive.

One row per Blink "network" (see app.blink.service.BlinkSyncModuleInfo) -
this includes sync-less networks (Mini/Doorbell-only, no physical hub;
is_physical_hub=False) alongside real hubs, mirroring how blinkpy itself
treats them uniformly.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.db import str_enum as _str_enum


class LocalStorageStatus(StrEnum):
    IDLE = "idle"
    REFRESHING = "refreshing"
    ERROR = "error"


class LocalItemStatus(StrEnum):
    AVAILABLE = "available"
    PREPARING = "preparing"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    ERROR = "error"


class SyncModule(Base):
    __tablename__ = "sync_modules"
    __table_args__ = (
        UniqueConstraint("blink_account_id", "network_id", name="uq_sync_modules_network"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    blink_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("blink_accounts.id", ondelete="cascade"),
        nullable=False,
        index=True,
    )
    network_id: Mapped[str] = mapped_column(Text, nullable=False)
    sync_id: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    serial: Mapped[str | None] = mapped_column(Text)
    firmware_version: Mapped[str | None] = mapped_column(Text)
    is_physical_hub: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    armed: Mapped[bool | None] = mapped_column(Boolean)
    online: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    local_storage_compatible: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    local_storage_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    local_storage_active: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    local_storage_manifest_id: Mapped[str | None] = mapped_column(Text)
    local_storage_status: Mapped[LocalStorageStatus] = mapped_column(
        _str_enum(LocalStorageStatus, "sync_module_local_storage_status", length=20),
        default=LocalStorageStatus.IDLE,
        server_default=LocalStorageStatus.IDLE.name,
    )
    local_storage_manifest_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    local_storage_manifest_refreshed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    local_storage_last_error: Mapped[str | None] = mapped_column(Text)

    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SyncModuleLocalItem(Base):
    """One clip listed in a Sync Module's local (USB) storage manifest.

    Deliberately its own table, not a Clip row - the cloud media-changed
    feed and this local-storage manifest share no identifier blinkpy
    exposes, so a clip that's both cloud-synced and still on the USB drive
    has no reliable way to detect the overlap. Kept separate to avoid
    risking duplicate Library entries; may be revisited once real-world
    usage shows how often that overlap actually happens.
    """

    __tablename__ = "sync_module_local_items"
    __table_args__ = (
        UniqueConstraint("sync_module_id", "blink_item_id", name="uq_sync_module_local_items_item"),
        Index("ix_sync_module_local_items_sync_module_id", "sync_module_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sync_module_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sync_modules.id", ondelete="cascade"), nullable=False
    )
    # set null, not cascade: a clip already downloaded (paid for in network
    # cost and disk space) stays meaningful even if the originating Camera
    # row is later removed/renamed - only its display attribution degrades.
    camera_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cameras.id", ondelete="set null")
    )
    # The manifest's own raw camera name, kept regardless of whether
    # camera_id resolves - the file explorer should show everything
    # physically on the drive, matched name or not.
    camera_name: Mapped[str] = mapped_column(Text, nullable=False)
    blink_item_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # False once a later manifest refresh no longer lists this item - the
    # Sync Module itself may have rotated/evicted it, but our own
    # downloaded copy (if any) is kept either way.
    present_on_device: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    status: Mapped[LocalItemStatus] = mapped_column(
        _str_enum(LocalItemStatus, "sync_module_local_item_status", length=20),
        default=LocalItemStatus.AVAILABLE,
        server_default=LocalItemStatus.AVAILABLE.name,
    )
    storage_path: Mapped[str | None] = mapped_column(Text)
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
