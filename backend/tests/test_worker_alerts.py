"""send_alert: quiet hours / dedup short-circuits, per-channel fan-out.

Delivery functions are faked at the names imported into
app.worker.tasks.alerts (never a real network call); dedup needs real
Redis semantics (atomic SET NX), so these tests swap worker_ctx's default
AsyncMock redis for the real `redis` fixture — everything else about
worker_ctx (a real sessionmaker, truncated tables) still applies.
"""

# pytest calls autouse fixtures implicitly; pyright can't see that usage.
# pyright: reportUnusedFunction=false

from datetime import UTC, datetime
from typing import Any

import pytest

from app.alerts.delivery import AlertDeliveryError
from app.alerts.schemas import AlertSettingsUpdate
from app.alerts.service import update_alert_settings
from app.config import get_settings
from app.worker.tasks.alerts import send_alert


@pytest.fixture(autouse=True)
def _reset_fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_discord(*_args: object, **_kwargs: object) -> None:
        return None

    async def fake_slack(*_args: object, **_kwargs: object) -> None:
        return None

    async def fake_email(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr("app.worker.tasks.alerts.send_discord", fake_discord)
    monkeypatch.setattr("app.worker.tasks.alerts.send_slack", fake_slack)
    monkeypatch.setattr("app.worker.tasks.alerts.send_email", fake_email)


async def _enable_discord(ctx: dict[str, Any]) -> None:
    async with ctx["sessionmaker"]() as session:
        await update_alert_settings(
            session,
            AlertSettingsUpdate(
                discord_enabled=True, discord_webhook_url="https://discord.example"
            ),
            get_settings().encryption_key,
        )


async def test_no_channels_enabled(worker_ctx: dict[str, Any], redis: object) -> None:
    worker_ctx["redis"] = redis
    result = await send_alert(worker_ctx, camera_id="cam-1", reason="suspicious", message="hi")
    assert result == "no_channels_enabled"


async def test_discord_success_returns_ok(worker_ctx: dict[str, Any], redis: object) -> None:
    worker_ctx["redis"] = redis
    await _enable_discord(worker_ctx)
    result = await send_alert(worker_ctx, camera_id="cam-1", reason="suspicious", message="hi")
    assert result == "ok"


async def test_discord_failure_with_no_other_channel_returns_failed(
    worker_ctx: dict[str, Any], redis: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker_ctx["redis"] = redis
    await _enable_discord(worker_ctx)

    async def failing_discord(*_args: object, **_kwargs: object) -> None:
        raise AlertDeliveryError("boom")

    monkeypatch.setattr("app.worker.tasks.alerts.send_discord", failing_discord)
    result = await send_alert(worker_ctx, camera_id="cam-1", reason="suspicious", message="hi")
    assert result == "failed"


async def test_one_channel_failing_does_not_block_another_from_sending(
    worker_ctx: dict[str, Any], redis: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker_ctx["redis"] = redis
    async with worker_ctx["sessionmaker"]() as session:
        await update_alert_settings(
            session,
            AlertSettingsUpdate(
                discord_enabled=True,
                discord_webhook_url="https://discord.example",
                slack_enabled=True,
                slack_webhook_url="https://slack.example",
            ),
            get_settings().encryption_key,
        )

    async def failing_discord(*_args: object, **_kwargs: object) -> None:
        raise AlertDeliveryError("boom")

    monkeypatch.setattr("app.worker.tasks.alerts.send_discord", failing_discord)
    result = await send_alert(worker_ctx, camera_id="cam-1", reason="suspicious", message="hi")
    assert result == "ok"  # slack still went through


async def test_slack_failure_with_no_other_channel_returns_failed(
    worker_ctx: dict[str, Any], redis: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker_ctx["redis"] = redis
    async with worker_ctx["sessionmaker"]() as session:
        await update_alert_settings(
            session,
            AlertSettingsUpdate(slack_enabled=True, slack_webhook_url="https://slack.example"),
            get_settings().encryption_key,
        )

    async def failing_slack(*_args: object, **_kwargs: object) -> None:
        raise AlertDeliveryError("boom")

    monkeypatch.setattr("app.worker.tasks.alerts.send_slack", failing_slack)
    result = await send_alert(worker_ctx, camera_id="cam-1", reason="suspicious", message="hi")
    assert result == "failed"


async def test_smtp_failure_with_no_other_channel_returns_failed(
    worker_ctx: dict[str, Any], redis: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker_ctx["redis"] = redis
    async with worker_ctx["sessionmaker"]() as session:
        await update_alert_settings(
            session,
            AlertSettingsUpdate(
                smtp_enabled=True,
                smtp_host="smtp.example.com",
                smtp_from_address="alerts@example.com",
                smtp_to_addresses=["me@example.com"],
            ),
            get_settings().encryption_key,
        )

    async def failing_email(*_args: object, **_kwargs: object) -> None:
        raise AlertDeliveryError("boom")

    monkeypatch.setattr("app.worker.tasks.alerts.send_email", failing_email)
    result = await send_alert(worker_ctx, camera_id="cam-1", reason="suspicious", message="hi")
    assert result == "failed"


async def test_smtp_success_returns_ok(worker_ctx: dict[str, Any], redis: object) -> None:
    worker_ctx["redis"] = redis
    async with worker_ctx["sessionmaker"]() as session:
        await update_alert_settings(
            session,
            AlertSettingsUpdate(
                smtp_enabled=True,
                smtp_host="smtp.example.com",
                smtp_from_address="alerts@example.com",
                smtp_to_addresses=["me@example.com"],
                smtp_password="hunter2",
            ),
            get_settings().encryption_key,
        )
    result = await send_alert(worker_ctx, camera_id="cam-1", reason="suspicious", message="hi")
    assert result == "ok"


async def test_quiet_hours_short_circuits_before_sending(
    worker_ctx: dict[str, Any], redis: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker_ctx["redis"] = redis
    await _enable_discord(worker_ctx)
    async with worker_ctx["sessionmaker"]() as session:
        await update_alert_settings(
            session,
            AlertSettingsUpdate(
                discord_enabled=True,
                discord_webhook_url="https://discord.example",
                quiet_hours_start=datetime(2026, 1, 1, 0, 0, tzinfo=UTC).time(),
                quiet_hours_end=datetime(2026, 1, 1, 23, 59, tzinfo=UTC).time(),
            ),
            get_settings().encryption_key,
        )

    async def unexpected_call(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("should not be called during quiet hours")

    monkeypatch.setattr("app.worker.tasks.alerts.send_discord", unexpected_call)
    result = await send_alert(worker_ctx, camera_id="cam-1", reason="suspicious", message="hi")
    assert result == "quiet_hours"


async def test_dedup_short_circuits_the_second_call(
    worker_ctx: dict[str, Any], redis: object
) -> None:
    worker_ctx["redis"] = redis
    await _enable_discord(worker_ctx)
    first = await send_alert(worker_ctx, camera_id="cam-1", reason="suspicious", message="hi")
    second = await send_alert(worker_ctx, camera_id="cam-1", reason="suspicious", message="hi")
    assert first == "ok"
    assert second == "deduped"
