"""Discord/Slack webhook posts and SMTP email — the three notification
channels, each independently optional and independently testable.

Discord/Slack take an injectable httpx client (matching the Moondream
provider's pattern) and SMTP calls stdlib ``smtplib`` inside
``asyncio.to_thread`` rather than adding an async SMTP dependency: it's a
handful of blocking calls behind one lock, not a hot path.
"""

import asyncio
import smtplib
from email.message import EmailMessage

import httpx

from app.alerts.models import AlertSettings
from app.logs import get_logger

logger = get_logger(__name__)

WEBHOOK_TIMEOUT_SECONDS = 15.0
SMTP_TIMEOUT_SECONDS = 15.0
DISCORD_MESSAGE_LIMIT = 2000


class AlertDeliveryError(Exception):
    """A channel failed to send — logged and reported, never retried
    indefinitely (a bad webhook URL or SMTP password won't fix itself)."""


async def send_discord(
    webhook_url: str, message: str, client: httpx.AsyncClient | None = None
) -> None:
    owned_client = client is None
    client = client or httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT_SECONDS)
    try:
        response = await client.post(webhook_url, json={"content": message[:DISCORD_MESSAGE_LIMIT]})
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise AlertDeliveryError(f"Discord delivery failed: {exc}") from exc
    finally:
        if owned_client:
            await client.aclose()


async def send_slack(
    webhook_url: str, message: str, client: httpx.AsyncClient | None = None
) -> None:
    owned_client = client is None
    client = client or httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT_SECONDS)
    try:
        response = await client.post(webhook_url, json={"text": message})
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise AlertDeliveryError(f"Slack delivery failed: {exc}") from exc
    finally:
        if owned_client:
            await client.aclose()


def _build_email(settings: AlertSettings, subject: str, body: str) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from_address
    message["To"] = ", ".join(settings.smtp_to_addresses)
    message.set_content(body)
    return message


def _send_smtp_sync(
    host: str, settings: AlertSettings, message: EmailMessage, password: str | None
) -> None:
    with smtplib.SMTP(host, settings.smtp_port, timeout=SMTP_TIMEOUT_SECONDS) as smtp:
        if settings.smtp_use_tls:
            smtp.starttls()
        if settings.smtp_username and password:
            smtp.login(settings.smtp_username, password)
        smtp.send_message(message)


async def send_email(
    settings: AlertSettings, subject: str, body: str, password: str | None
) -> None:
    if not settings.smtp_host or not settings.smtp_from_address or not settings.smtp_to_addresses:
        raise AlertDeliveryError("SMTP is not fully configured.")
    host = settings.smtp_host
    message = _build_email(settings, subject, body)
    try:
        await asyncio.to_thread(_send_smtp_sync, host, settings, message, password)
    except (smtplib.SMTPException, OSError) as exc:
        raise AlertDeliveryError(f"SMTP delivery failed: {exc}") from exc
