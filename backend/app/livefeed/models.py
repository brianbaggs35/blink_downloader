"""Live View and Security Feed settings: two household-wide singletons,
same pattern as AlertSettings/AISettings - one row, get-or-create.

These settings rows only ever describe the snapshot side of each feature
(default camera, auto-refresh timing, chosen cameras/columns) - Live View's
real streaming sessions are process-local runtime state, not settings, and
live in app.livefeed.live_stream (see docs/ARCHITECTURE.md#live-view--security-feed).
Security Feed itself stays snapshot-only: a passively-polled multi-camera
grid showing whatever Blink's own motion-triggered capture last produced.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.db import str_enum as _str_enum

SINGLETON_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

DEFAULT_LIVE_VIEW_REFRESH_SECONDS = 10
DEFAULT_SECURITY_FEED_REFRESH_SECONDS = 20
DEFAULT_SECURITY_FEED_COLUMNS = 2


class SecurityFeedRefreshMode(StrEnum):
    # Forces a fresh capture from the camera every refresh_interval_seconds
    # (admin-only server-side - see app.livefeed.service.get_camera_preview
    # via api/cameras.py's force flag; a non-admin viewer transparently
    # falls back to MOTION's passive behavior instead of erroring).
    INTERVAL = "interval"
    # Never forces a capture - just re-polls whatever Blink's cloud already
    # has cached, which already reflects real motion-triggered updates.
    MOTION = "motion"


class LiveViewSettings(Base):
    __tablename__ = "live_view_settings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)

    default_camera_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cameras.id", ondelete="set null")
    )
    auto_refresh_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    auto_refresh_interval_seconds: Mapped[int] = mapped_column(
        Integer,
        default=DEFAULT_LIVE_VIEW_REFRESH_SECONDS,
        server_default=str(DEFAULT_LIVE_VIEW_REFRESH_SECONDS),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SecurityFeedSettings(Base):
    __tablename__ = "security_feed_settings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)

    # Ordered camera ids to show; empty means "every enabled camera",
    # so the dashboard is useful with zero configuration.
    camera_ids: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    columns: Mapped[int] = mapped_column(
        Integer,
        default=DEFAULT_SECURITY_FEED_COLUMNS,
        server_default=str(DEFAULT_SECURITY_FEED_COLUMNS),
    )
    refresh_interval_seconds: Mapped[int] = mapped_column(
        Integer,
        default=DEFAULT_SECURITY_FEED_REFRESH_SECONDS,
        server_default=str(DEFAULT_SECURITY_FEED_REFRESH_SECONDS),
    )
    refresh_mode: Mapped[SecurityFeedRefreshMode] = mapped_column(
        _str_enum(SecurityFeedRefreshMode, "security_feed_refresh_mode", length=10),
        default=SecurityFeedRefreshMode.INTERVAL,
        server_default=SecurityFeedRefreshMode.INTERVAL.name,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
