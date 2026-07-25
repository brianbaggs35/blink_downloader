"""Discord/Slack webhook posts (httpx.MockTransport, never a real network
call) and SMTP email (smtplib.SMTP faked module-wide — app.alerts.delivery
accesses it as ``smtplib.SMTP(...)``, a module-qualified reference, so
patching the shared module attribute reaches it directly)."""

# pytest calls autouse fixtures implicitly; pyright can't see that usage.
# pyright: reportUnusedFunction=false

import smtplib
from typing import ClassVar

import httpx
import pytest

from app.alerts.delivery import AlertDeliveryError, send_discord, send_email, send_slack
from app.alerts.models import AlertSettings


def _transport(handler: object) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]


async def test_send_discord_success() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(204)

    await send_discord("https://discord.example/webhook", "hello", client=_transport(handler))
    assert captured["url"] == "https://discord.example/webhook"


async def test_send_discord_truncates_long_messages() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content
        return httpx.Response(204)

    await send_discord("https://discord.example/webhook", "x" * 3000, client=_transport(handler))
    assert len(captured["body"]) < 2100  # type: ignore[arg-type]


async def test_send_discord_raises_on_http_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    with pytest.raises(AlertDeliveryError, match="Discord delivery failed"):
        await send_discord("https://discord.example/webhook", "hello", client=_transport(handler))


async def test_send_slack_success() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    await send_slack("https://slack.example/webhook", "hello", client=_transport(handler))


async def test_send_slack_raises_on_http_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    with pytest.raises(AlertDeliveryError, match="Slack delivery failed"):
        await send_slack("https://slack.example/webhook", "hello", client=_transport(handler))


_RealAsyncClient = httpx.AsyncClient


def _patch_client_factory(
    monkeypatch: pytest.MonkeyPatch, created: list[httpx.AsyncClient]
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    def fake_client(**_kwargs: object) -> httpx.AsyncClient:
        client = _RealAsyncClient(transport=httpx.MockTransport(handler))
        created.append(client)
        return client

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)


async def test_send_discord_without_a_client_owns_and_closes_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[httpx.AsyncClient] = []
    _patch_client_factory(monkeypatch, created)
    await send_discord("https://discord.example/webhook", "hello")
    assert created[0].is_closed


async def test_send_slack_without_a_client_owns_and_closes_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[httpx.AsyncClient] = []
    _patch_client_factory(monkeypatch, created)
    await send_slack("https://slack.example/webhook", "hello")
    assert created[0].is_closed


def make_smtp_settings(**overrides: object) -> AlertSettings:
    defaults: dict[str, object] = {
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_from_address": "alerts@example.com",
        "smtp_to_addresses": ["me@example.com"],
        "smtp_use_tls": True,
        "smtp_username": "alerts@example.com",
    }
    defaults.update(overrides)
    return AlertSettings(**defaults)  # type: ignore[arg-type]


class FakeSMTP:
    instances: ClassVar[list[FakeSMTP]] = []
    should_fail: ClassVar[bool] = False

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host, self.port, self.timeout = host, port, timeout
        self.started_tls = False
        self.logged_in: tuple[str, str] | None = None
        self.sent_message: object | None = None
        FakeSMTP.instances.append(self)
        if FakeSMTP.should_fail:
            raise TimeoutError("could not connect")

    def __enter__(self) -> FakeSMTP:
        return self

    def __exit__(self, *_args: object) -> None:
        pass

    def starttls(self) -> None:
        self.started_tls = True

    def login(self, username: str, password: str) -> None:
        self.logged_in = (username, password)

    def send_message(self, message: object) -> None:
        self.sent_message = message


@pytest.fixture(autouse=True)
def _reset_fake_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeSMTP.instances = []
    FakeSMTP.should_fail = False
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)


async def test_send_email_success_with_tls_and_login() -> None:
    settings = make_smtp_settings()
    await send_email(settings, "Subject", "Body text", password="hunter2")

    smtp = FakeSMTP.instances[-1]
    assert smtp.started_tls is True
    assert smtp.logged_in == ("alerts@example.com", "hunter2")
    assert smtp.sent_message is not None


async def test_send_email_skips_login_without_a_password() -> None:
    settings = make_smtp_settings()
    await send_email(settings, "Subject", "Body", password=None)
    assert FakeSMTP.instances[-1].logged_in is None


async def test_send_email_skips_starttls_when_disabled() -> None:
    settings = make_smtp_settings(smtp_use_tls=False)
    await send_email(settings, "Subject", "Body", password="hunter2")
    assert FakeSMTP.instances[-1].started_tls is False


async def test_send_email_raises_when_not_fully_configured() -> None:
    settings = make_smtp_settings(smtp_host=None)
    with pytest.raises(AlertDeliveryError, match="not fully configured"):
        await send_email(settings, "Subject", "Body", password=None)


async def test_send_email_wraps_smtp_errors() -> None:
    FakeSMTP.should_fail = True
    settings = make_smtp_settings()
    with pytest.raises(AlertDeliveryError, match="SMTP delivery failed"):
        await send_email(settings, "Subject", "Body", password="hunter2")
