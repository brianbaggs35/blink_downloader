"""Alert delivery settings: one household, one set of channels.

Discord/Slack webhook URLs and the SMTP password are encrypted at rest
(:mod:`app.security.crypto`) — decryptable only for actually sending an
alert, and shown back to the admin only inside Settings.
"""

import uuid
from datetime import datetime, time

from sqlalchemy import Boolean, DateTime, Float, Integer, Text, Time, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

SINGLETON_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

DEFAULT_SUSPICION_THRESHOLD = 0.5
DEFAULT_DEDUP_WINDOW_MINUTES = 15


class AlertSettings(Base):
    __tablename__ = "alert_settings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)

    discord_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    encrypted_discord_webhook_url: Mapped[str | None] = mapped_column(Text)

    slack_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    encrypted_slack_webhook_url: Mapped[str | None] = mapped_column(Text)

    smtp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    smtp_host: Mapped[str | None] = mapped_column(Text)
    smtp_port: Mapped[int] = mapped_column(Integer, default=587, server_default="587")
    smtp_username: Mapped[str | None] = mapped_column(Text)
    encrypted_smtp_password: Mapped[str | None] = mapped_column(Text)
    smtp_use_tls: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    smtp_from_address: Mapped[str | None] = mapped_column(Text)
    smtp_to_addresses: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")

    alert_on_suspicious_clip: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    suspicion_alert_threshold: Mapped[float] = mapped_column(
        Float, default=DEFAULT_SUSPICION_THRESHOLD, server_default=str(DEFAULT_SUSPICION_THRESHOLD)
    )
    alert_on_vehicle_proximity: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )

    quiet_hours_start: Mapped[time | None] = mapped_column(Time)
    quiet_hours_end: Mapped[time | None] = mapped_column(Time)
    dedup_window_minutes: Mapped[int] = mapped_column(
        Integer,
        default=DEFAULT_DEDUP_WINDOW_MINUTES,
        server_default=str(DEFAULT_DEDUP_WINDOW_MINUTES),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
