"""Alert delivery: fan out to every enabled channel, after quiet hours and
dedup checks. Triggered by analyze_clip after a suspicious analysis or a
vehicle-proximity breach — never by the pipeline calling delivery code
directly, so a slow/broken alert channel can never hold up analysis.
"""

from datetime import UTC, datetime
from typing import Any

from app.alerts.delivery import AlertDeliveryError, send_discord, send_email, send_slack
from app.alerts.service import get_alert_settings, is_within_quiet_hours, should_dedupe
from app.config import get_settings
from app.logs import get_logger
from app.security.crypto import SecretBox

logger = get_logger(__name__)

SEND_ALERT_JOB_NAME = "send_alert"


async def send_alert(ctx: dict[Any, Any], *, camera_id: str, reason: str, message: str) -> str:
    settings = get_settings()
    async with ctx["sessionmaker"]() as session:
        alert_settings = await get_alert_settings(session)

        if is_within_quiet_hours(alert_settings, datetime.now(UTC)):
            return "quiet_hours"
        if await should_dedupe(ctx["redis"], alert_settings, f"{camera_id}:{reason}"):
            return "deduped"

        box = SecretBox(settings.encryption_key)
        sent_any = False
        failures: list[str] = []

        if alert_settings.discord_enabled and alert_settings.encrypted_discord_webhook_url:
            try:
                webhook_url = box.decrypt(alert_settings.encrypted_discord_webhook_url)
                await send_discord(webhook_url, message)
                sent_any = True
            except AlertDeliveryError as exc:
                failures.append(str(exc))
                logger.warning("alerts.discord_failed", reason=reason, error=str(exc))

        if alert_settings.slack_enabled and alert_settings.encrypted_slack_webhook_url:
            try:
                await send_slack(box.decrypt(alert_settings.encrypted_slack_webhook_url), message)
                sent_any = True
            except AlertDeliveryError as exc:
                failures.append(str(exc))
                logger.warning("alerts.slack_failed", reason=reason, error=str(exc))

        if alert_settings.smtp_enabled:
            password = (
                box.decrypt(alert_settings.encrypted_smtp_password)
                if alert_settings.encrypted_smtp_password
                else None
            )
            try:
                await send_email(alert_settings, f"Blink AI Security: {reason}", message, password)
                sent_any = True
            except AlertDeliveryError as exc:
                failures.append(str(exc))
                logger.warning("alerts.smtp_failed", reason=reason, error=str(exc))

        if sent_any:
            logger.info("alerts.sent", reason=reason, camera_id=camera_id, failures=len(failures))
            return "ok"
        if failures:
            return "failed"
        return "no_channels_enabled"
