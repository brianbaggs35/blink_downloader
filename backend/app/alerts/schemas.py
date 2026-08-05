"""Pydantic schemas for the Alerts settings API surface."""

from datetime import time

from pydantic import BaseModel, EmailStr, Field


class AlertSettingsRead(BaseModel):
    discord_enabled: bool
    discord_webhook_set: bool
    slack_enabled: bool
    slack_webhook_set: bool
    smtp_enabled: bool
    smtp_host: str | None
    smtp_port: int
    smtp_username: str | None
    smtp_password_set: bool
    smtp_use_tls: bool
    smtp_from_address: str | None
    smtp_to_addresses: list[str]
    alert_on_suspicious_clip: bool
    suspicion_alert_threshold: float
    alert_on_vehicle_proximity: bool
    alert_on_low_battery: bool
    quiet_hours_start: time | None
    quiet_hours_end: time | None
    dedup_window_minutes: int


class AlertSettingsUpdate(BaseModel):
    discord_enabled: bool = False
    discord_webhook_url: str | None = None
    """None leaves the stored webhook untouched; "" clears it."""

    slack_enabled: bool = False
    slack_webhook_url: str | None = None

    smtp_enabled: bool = False
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True
    smtp_from_address: EmailStr | None = None
    smtp_to_addresses: list[EmailStr] = Field(default_factory=list, max_length=20)

    alert_on_suspicious_clip: bool = True
    suspicion_alert_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    alert_on_vehicle_proximity: bool = True
    alert_on_low_battery: bool = True

    quiet_hours_start: time | None = None
    quiet_hours_end: time | None = None
    dedup_window_minutes: int = Field(default=15, ge=0, le=1440)


class AlertTestResult(BaseModel):
    ok: bool
    detail: str


class AlertTestResponse(BaseModel):
    discord: AlertTestResult | None = None
    slack: AlertTestResult | None = None
    smtp: AlertTestResult | None = None
