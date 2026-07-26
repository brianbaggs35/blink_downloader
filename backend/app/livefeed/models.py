"""Live View and Security Feed settings: two household-wide singletons,
same pattern as AlertSettings/AISettings - one row, get-or-create.

Neither Blink nor blinkpy expose real browser-playable video streaming
(``get_liveview()`` returns a raw ``rtsps://``/``immis://`` URL no browser
can play without a transcoding relay this project doesn't build). Both
features are snapshot-based instead: Live View shows one camera's current
image with an on-demand forced-refresh action; Security Feed is a
passively-polled multi-camera grid showing whatever Blink's own
motion-triggered capture last produced. See docs/LIVE_VIEW.md.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

SINGLETON_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

DEFAULT_LIVE_VIEW_REFRESH_SECONDS = 10
DEFAULT_SECURITY_FEED_REFRESH_SECONDS = 20
DEFAULT_SECURITY_FEED_COLUMNS = 2


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

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
