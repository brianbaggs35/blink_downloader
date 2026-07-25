"""/api/alerts/settings: admin-only configuration + a test-send endpoint.

Delivery is faked at the names imported into app.api.alerts (never a real
network call/SMTP connection)."""

# pytest calls autouse fixtures implicitly; pyright can't see that usage.
# pyright: reportUnusedFunction=false

from typing import ClassVar

import pytest
from httpx import AsyncClient

from app.alerts.delivery import AlertDeliveryError


class FakeDelivery:
    discord_should_fail: ClassVar[bool] = False
    slack_should_fail: ClassVar[bool] = False
    smtp_should_fail: ClassVar[bool] = False

    @staticmethod
    async def discord(*_args: object, **_kwargs: object) -> None:
        if FakeDelivery.discord_should_fail:
            raise AlertDeliveryError("discord boom")

    @staticmethod
    async def slack(*_args: object, **_kwargs: object) -> None:
        if FakeDelivery.slack_should_fail:
            raise AlertDeliveryError("slack boom")

    @staticmethod
    async def smtp(*_args: object, **_kwargs: object) -> None:
        if FakeDelivery.smtp_should_fail:
            raise AlertDeliveryError("smtp boom")


@pytest.fixture(autouse=True)
def _reset_fake_delivery(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeDelivery.discord_should_fail = False
    FakeDelivery.slack_should_fail = False
    FakeDelivery.smtp_should_fail = False
    monkeypatch.setattr("app.api.alerts.send_discord", FakeDelivery.discord)
    monkeypatch.setattr("app.api.alerts.send_slack", FakeDelivery.slack)
    monkeypatch.setattr("app.api.alerts.send_email", FakeDelivery.smtp)


async def test_get_requires_authentication(client: AsyncClient) -> None:
    assert (await client.get("/api/alerts/settings")).status_code == 401


async def test_get_requires_admin(viewer_client: AsyncClient) -> None:
    assert (await viewer_client.get("/api/alerts/settings")).status_code == 403


async def test_get_defaults(admin_client: AsyncClient) -> None:
    response = await admin_client.get("/api/alerts/settings")
    assert response.status_code == 200
    body = response.json()
    assert body["discord_enabled"] is False
    assert body["discord_webhook_set"] is False
    assert body["dedup_window_minutes"] == 15


async def test_put_requires_admin(viewer_client: AsyncClient) -> None:
    response = await viewer_client.put("/api/alerts/settings", json={})
    assert response.status_code == 403


async def test_put_updates_and_never_echoes_secrets(admin_client: AsyncClient) -> None:
    response = await admin_client.put(
        "/api/alerts/settings",
        json={
            "discord_enabled": True,
            "discord_webhook_url": "https://discord.example/super-secret",
            "smtp_enabled": True,
            "smtp_host": "smtp.example.com",
            "smtp_from_address": "alerts@example.com",
            "smtp_to_addresses": ["me@example.com"],
            "smtp_password": "hunter2",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["discord_enabled"] is True
    assert body["discord_webhook_set"] is True
    assert body["smtp_password_set"] is True
    assert "super-secret" not in response.text
    assert "hunter2" not in response.text


async def test_put_rejects_invalid_email(admin_client: AsyncClient) -> None:
    response = await admin_client.put(
        "/api/alerts/settings", json={"smtp_to_addresses": ["not-an-email"]}
    )
    assert response.status_code == 422


async def test_put_rejects_out_of_range_threshold(admin_client: AsyncClient) -> None:
    response = await admin_client.put(
        "/api/alerts/settings", json={"suspicion_alert_threshold": 2.0}
    )
    assert response.status_code == 422


async def test_test_endpoint_requires_admin(viewer_client: AsyncClient) -> None:
    assert (await viewer_client.post("/api/alerts/settings/test")).status_code == 403


async def test_test_endpoint_with_no_channels_configured(admin_client: AsyncClient) -> None:
    response = await admin_client.post("/api/alerts/settings/test")
    assert response.status_code == 200
    body = response.json()
    assert body == {"discord": None, "slack": None, "smtp": None}


async def test_test_endpoint_reports_success_and_failure_per_channel(
    admin_client: AsyncClient,
) -> None:
    await admin_client.put(
        "/api/alerts/settings",
        json={
            "discord_enabled": True,
            "discord_webhook_url": "https://discord.example",
            "slack_enabled": True,
            "slack_webhook_url": "https://slack.example",
            "smtp_enabled": True,
            "smtp_host": "smtp.example.com",
            "smtp_from_address": "alerts@example.com",
            "smtp_to_addresses": ["me@example.com"],
        },
    )
    FakeDelivery.slack_should_fail = True

    response = await admin_client.post("/api/alerts/settings/test")
    assert response.status_code == 200
    body = response.json()
    assert body["discord"] == {"ok": True, "detail": "Sent."}
    assert body["slack"]["ok"] is False
    assert "slack boom" in body["slack"]["detail"]
    assert body["smtp"] == {"ok": True, "detail": "Sent."}
