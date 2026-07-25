"""Settings > Alerts: channel configuration (admin-only) and a test-send
endpoint that exercises every currently-configured channel at once."""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.delivery import AlertDeliveryError, send_discord, send_email, send_slack
from app.alerts.models import AlertSettings
from app.alerts.schemas import (
    AlertSettingsRead,
    AlertSettingsUpdate,
    AlertTestResponse,
    AlertTestResult,
)
from app.alerts.service import get_alert_settings, update_alert_settings
from app.config import get_settings
from app.db import get_session
from app.logs import get_logger
from app.security.crypto import SecretBox
from app.users.auth import current_superuser

logger = get_logger(__name__)

router = APIRouter(prefix="/alerts", tags=["alerts"])

TEST_MESSAGE = "This is a test alert from your Blink AI Security Platform."


def _read(row: AlertSettings) -> AlertSettingsRead:
    return AlertSettingsRead(
        discord_enabled=row.discord_enabled,
        discord_webhook_set=bool(row.encrypted_discord_webhook_url),
        slack_enabled=row.slack_enabled,
        slack_webhook_set=bool(row.encrypted_slack_webhook_url),
        smtp_enabled=row.smtp_enabled,
        smtp_host=row.smtp_host,
        smtp_port=row.smtp_port,
        smtp_username=row.smtp_username,
        smtp_password_set=bool(row.encrypted_smtp_password),
        smtp_use_tls=row.smtp_use_tls,
        smtp_from_address=row.smtp_from_address,
        smtp_to_addresses=row.smtp_to_addresses,
        alert_on_suspicious_clip=row.alert_on_suspicious_clip,
        suspicion_alert_threshold=row.suspicion_alert_threshold,
        alert_on_vehicle_proximity=row.alert_on_vehicle_proximity,
        quiet_hours_start=row.quiet_hours_start,
        quiet_hours_end=row.quiet_hours_end,
        dedup_window_minutes=row.dedup_window_minutes,
    )


@router.get("/settings", response_model=AlertSettingsRead)
async def get_settings_endpoint(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> AlertSettingsRead:
    return _read(await get_alert_settings(session))


@router.put("/settings", response_model=AlertSettingsRead)
async def put_settings(
    payload: AlertSettingsUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> AlertSettingsRead:
    row = await update_alert_settings(session, payload, get_settings().encryption_key)
    logger.info("settings.alerts_updated")
    return _read(row)


async def _try_send(action: Callable[[], Awaitable[None]]) -> AlertTestResult:
    try:
        await action()
    except AlertDeliveryError as exc:
        return AlertTestResult(ok=False, detail=str(exc))
    return AlertTestResult(ok=True, detail="Sent.")


@router.post("/settings/test", response_model=AlertTestResponse)
async def test_channels(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> AlertTestResponse:
    row = await get_alert_settings(session)
    box = SecretBox(get_settings().encryption_key)
    response = AlertTestResponse()

    if row.discord_enabled and row.encrypted_discord_webhook_url:
        discord_url = box.decrypt(row.encrypted_discord_webhook_url)
        response.discord = await _try_send(lambda: send_discord(discord_url, TEST_MESSAGE))

    if row.slack_enabled and row.encrypted_slack_webhook_url:
        slack_url = box.decrypt(row.encrypted_slack_webhook_url)
        response.slack = await _try_send(lambda: send_slack(slack_url, TEST_MESSAGE))

    if row.smtp_enabled:
        password = box.decrypt(row.encrypted_smtp_password) if row.encrypted_smtp_password else None
        response.smtp = await _try_send(
            lambda: send_email(row, "Blink AI Security: test alert", TEST_MESSAGE, password)
        )

    return response
