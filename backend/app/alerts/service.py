"""Alert settings CRUD, plus the decision logic for whether to notify at
all: quiet hours and a Redis-backed dedup window.

Dedup state is intentionally not a DB table: it's short-lived rate-limiting
state (did we already alert for this camera+reason in the last N minutes),
a natural fit for a TTL'd Redis key, matching the worker heartbeat's use of
Redis for the same kind of ephemeral fact.
"""

from datetime import datetime

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.models import SINGLETON_ID, AlertSettings
from app.alerts.schemas import AlertSettingsUpdate
from app.security.crypto import SecretBox

DEDUP_KEY_PREFIX = "blink:alert:dedup:"


async def get_alert_settings(session: AsyncSession) -> AlertSettings:
    row = await session.get(AlertSettings, SINGLETON_ID)
    if row is None:
        row = AlertSettings(id=SINGLETON_ID)
        session.add(row)
        await session.flush()
    return row


def _apply_secret(row: AlertSettings, attr: str, box: SecretBox, value: str | None) -> None:
    if value is None:
        return
    setattr(row, attr, box.encrypt(value) if value else None)


async def update_alert_settings(
    session: AsyncSession, payload: AlertSettingsUpdate, encryption_key: str
) -> AlertSettings:
    row = await get_alert_settings(session)
    box = SecretBox(encryption_key)

    row.discord_enabled = payload.discord_enabled
    _apply_secret(row, "encrypted_discord_webhook_url", box, payload.discord_webhook_url)

    row.slack_enabled = payload.slack_enabled
    _apply_secret(row, "encrypted_slack_webhook_url", box, payload.slack_webhook_url)

    row.smtp_enabled = payload.smtp_enabled
    row.smtp_host = payload.smtp_host
    row.smtp_port = payload.smtp_port
    row.smtp_username = payload.smtp_username
    _apply_secret(row, "encrypted_smtp_password", box, payload.smtp_password)
    row.smtp_use_tls = payload.smtp_use_tls
    row.smtp_from_address = payload.smtp_from_address
    row.smtp_to_addresses = list(payload.smtp_to_addresses)

    row.alert_on_suspicious_clip = payload.alert_on_suspicious_clip
    row.suspicion_alert_threshold = payload.suspicion_alert_threshold
    row.alert_on_vehicle_proximity = payload.alert_on_vehicle_proximity

    row.quiet_hours_start = payload.quiet_hours_start
    row.quiet_hours_end = payload.quiet_hours_end
    row.dedup_window_minutes = payload.dedup_window_minutes

    await session.commit()
    await session.refresh(row)
    return row


def is_within_quiet_hours(settings: AlertSettings, now: datetime) -> bool:
    if settings.quiet_hours_start is None or settings.quiet_hours_end is None:
        return False
    current = now.time()
    start, end = settings.quiet_hours_start, settings.quiet_hours_end
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end  # wraps midnight, e.g. 22:00-06:00


async def should_dedupe(redis: Redis, settings: AlertSettings, dedup_key: str) -> bool:
    """True if an alert for this key was already sent within the dedup
    window (the caller should skip sending). The Redis SET NX is the
    dedup claim itself — the first caller within the window wins it."""
    if settings.dedup_window_minutes <= 0:
        return False
    key = f"{DEDUP_KEY_PREFIX}{dedup_key}"
    claimed = await redis.set(key, "1", ex=settings.dedup_window_minutes * 60, nx=True)
    return not claimed
