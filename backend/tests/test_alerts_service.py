"""Alert settings CRUD (tri-state secrets, same pattern as app.ai.service),
quiet-hours math, and Redis-backed dedup."""

from datetime import UTC, datetime, time

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.models import SINGLETON_ID, AlertSettings
from app.alerts.schemas import AlertSettingsUpdate
from app.alerts.service import (
    get_alert_settings,
    is_within_quiet_hours,
    should_dedupe,
    update_alert_settings,
)
from app.config import get_settings


async def test_get_alert_settings_creates_the_row_on_first_read(app_session: AsyncSession) -> None:
    row = await get_alert_settings(app_session)
    assert row.id == SINGLETON_ID
    assert row.discord_enabled is False
    assert row.dedup_window_minutes == 15


async def test_update_sets_channel_fields_and_encrypts_secrets(app_session: AsyncSession) -> None:
    payload = AlertSettingsUpdate(
        discord_enabled=True,
        discord_webhook_url="https://discord.example/webhook",
        smtp_enabled=True,
        smtp_host="smtp.example.com",
        smtp_from_address="alerts@example.com",
        smtp_to_addresses=["me@example.com"],
        smtp_password="hunter2",
    )
    row = await update_alert_settings(app_session, payload, get_settings().encryption_key)
    assert row.discord_enabled is True
    assert row.encrypted_discord_webhook_url is not None
    assert row.encrypted_discord_webhook_url != "https://discord.example/webhook"
    assert row.encrypted_smtp_password is not None
    assert row.smtp_to_addresses == ["me@example.com"]


async def test_update_with_none_secret_leaves_it_untouched(app_session: AsyncSession) -> None:
    encryption_key = get_settings().encryption_key
    first = AlertSettingsUpdate(discord_enabled=True, discord_webhook_url="https://original")
    row = await update_alert_settings(app_session, first, encryption_key)
    original = row.encrypted_discord_webhook_url

    second = AlertSettingsUpdate(discord_enabled=False, discord_webhook_url=None)
    row = await update_alert_settings(app_session, second, encryption_key)
    assert row.discord_enabled is False
    assert row.encrypted_discord_webhook_url == original


async def test_update_with_empty_string_secret_clears_it(app_session: AsyncSession) -> None:
    encryption_key = get_settings().encryption_key
    first = AlertSettingsUpdate(discord_enabled=True, discord_webhook_url="https://original")
    await update_alert_settings(app_session, first, encryption_key)

    second = AlertSettingsUpdate(discord_enabled=True, discord_webhook_url="")
    row = await update_alert_settings(app_session, second, encryption_key)
    assert row.encrypted_discord_webhook_url is None


# ------------------------------------------------------------- quiet hours


def make_settings(**overrides: object) -> AlertSettings:
    defaults: dict[str, object] = {}
    defaults.update(overrides)
    return AlertSettings(**defaults)  # type: ignore[arg-type]


def test_quiet_hours_none_means_never_quiet() -> None:
    settings = make_settings(quiet_hours_start=None, quiet_hours_end=None)
    assert is_within_quiet_hours(settings, datetime(2026, 7, 20, 2, 0, tzinfo=UTC)) is False


def test_quiet_hours_same_day_range() -> None:
    settings = make_settings(quiet_hours_start=time(22, 0), quiet_hours_end=time(23, 0))
    assert is_within_quiet_hours(settings, datetime(2026, 7, 20, 22, 30, tzinfo=UTC)) is True
    assert is_within_quiet_hours(settings, datetime(2026, 7, 20, 21, 0, tzinfo=UTC)) is False


def test_quiet_hours_wraps_midnight() -> None:
    settings = make_settings(quiet_hours_start=time(22, 0), quiet_hours_end=time(6, 0))
    assert is_within_quiet_hours(settings, datetime(2026, 7, 20, 23, 0, tzinfo=UTC)) is True
    assert is_within_quiet_hours(settings, datetime(2026, 7, 20, 3, 0, tzinfo=UTC)) is True
    assert is_within_quiet_hours(settings, datetime(2026, 7, 20, 12, 0, tzinfo=UTC)) is False


# ------------------------------------------------------------------ dedup


async def test_should_dedupe_first_call_claims_and_returns_false(redis: Redis) -> None:
    settings = make_settings(dedup_window_minutes=15)
    assert await should_dedupe(redis, settings, "cam-1:suspicious") is False


async def test_should_dedupe_second_call_within_window_is_true(redis: Redis) -> None:
    settings = make_settings(dedup_window_minutes=15)
    assert await should_dedupe(redis, settings, "cam-1:suspicious") is False
    assert await should_dedupe(redis, settings, "cam-1:suspicious") is True


async def test_should_dedupe_different_keys_are_independent(redis: Redis) -> None:
    settings = make_settings(dedup_window_minutes=15)
    assert await should_dedupe(redis, settings, "cam-1:suspicious") is False
    assert await should_dedupe(redis, settings, "cam-2:suspicious") is False


async def test_should_dedupe_disabled_when_window_is_zero(redis: Redis) -> None:
    settings = make_settings(dedup_window_minutes=0)
    assert await should_dedupe(redis, settings, "cam-1:suspicious") is False
    assert await should_dedupe(redis, settings, "cam-1:suspicious") is False
