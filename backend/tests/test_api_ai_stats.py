"""/api/ai/stats and /api/ai/usage: aggregate numbers for the AI and AI
Usage tabs."""

import uuid
from datetime import UTC, datetime

from fastapi import FastAPI
from httpx import AsyncClient

from app.ai.models import (
    AIProviderKind,
    AIUsage,
    Analysis,
    AnalysisTier,
    Feedback,
    FeedbackVerdict,
    SuspicionLabel,
)
from app.blink.models import BlinkAccount, Camera, Clip
from app.config import get_settings
from app.security.crypto import SecretBox
from app.users.models import User
from app.vehicles.models import ProximityEvent, Vehicle


async def _make_camera_and_clip(app: FastAPI) -> tuple[Camera, Clip]:
    async with app.state.sessionmaker() as session:
        box = SecretBox(get_settings().encryption_key)
        account = BlinkAccount(
            encrypted_username=box.encrypt("u"),
            encrypted_password=box.encrypt("p"),
            encrypted_token_data=box.encrypt("{}"),
        )
        session.add(account)
        await session.flush()
        camera = Camera(
            blink_account_id=account.id,
            blink_camera_id=f"cam-{uuid.uuid4()}",
            blink_network_id="net-1",
            name="Driveway",
            camera_type="catalina",
        )
        session.add(camera)
        await session.flush()
        clip = Clip(
            camera_id=camera.id,
            blink_clip_id=f"/media/{uuid.uuid4()}.mp4",
            recorded_at=datetime(2026, 7, 20, tzinfo=UTC),
            raw_metadata={},
        )
        session.add(clip)
        await session.commit()
        await session.refresh(camera)
        await session.refresh(clip)
        return camera, clip


async def _make_analysis(app: FastAPI, clip: Clip, **overrides: object) -> Analysis:
    async with app.state.sessionmaker() as session:
        defaults: dict[str, object] = {
            "clip_id": clip.id,
            "summary": "Nothing unusual.",
            "suspicion_score": 0.1,
            "suspicion_label": SuspicionLabel.ROUTINE,
            "tier": AnalysisTier.TIER1,
        }
        defaults.update(overrides)
        analysis = Analysis(**defaults)  # type: ignore[arg-type]
        session.add(analysis)
        await session.commit()
        await session.refresh(analysis)
        return analysis


async def test_stats_requires_authentication(client: AsyncClient) -> None:
    assert (await client.get("/api/ai/stats")).status_code == 401


async def test_stats_all_zero_with_no_data(admin_client: AsyncClient) -> None:
    response = await admin_client.get("/api/ai/stats")
    assert response.status_code == 200
    body = response.json()
    assert body["total_analyzed"] == 0
    assert body["suspicious_count"] == 0
    assert body["vehicle_proximity_breaches"] == 0
    assert body["total_feedback"] == 0


async def test_stats_counts_by_label_and_escalation(
    admin_client: AsyncClient, app: FastAPI
) -> None:
    _camera, clip_a = await _make_camera_and_clip(app)
    _camera2, clip_b = await _make_camera_and_clip(app)
    await _make_analysis(app, clip_a, suspicion_label=SuspicionLabel.SUSPICIOUS, escalated=True)
    await _make_analysis(app, clip_b, suspicion_label=SuspicionLabel.ROUTINE)

    response = await admin_client.get("/api/ai/stats")
    body = response.json()
    assert body["total_analyzed"] == 2
    assert body["suspicious_count"] == 1
    assert body["routine_count"] == 1
    assert body["escalated_count"] == 1
    assert body["analyzed_last_7_days"] == 2  # both analyses were just created


async def test_stats_only_counts_current_analyses(admin_client: AsyncClient, app: FastAPI) -> None:
    _camera, clip = await _make_camera_and_clip(app)
    await _make_analysis(app, clip, is_current=False)
    response = await admin_client.get("/api/ai/stats")
    assert response.json()["total_analyzed"] == 0


async def test_stats_counts_vehicle_proximity_breaches(
    admin_client: AsyncClient, app: FastAPI
) -> None:
    camera, clip = await _make_camera_and_clip(app)
    async with app.state.sessionmaker() as session:
        vehicle = Vehicle(
            camera_id=camera.id,
            description="Car",
            outline_points=[[0.3, 0.5], [0.7, 0.5], [0.7, 0.8]],
        )
        session.add(vehicle)
        await session.flush()
        session.add(
            ProximityEvent(
                vehicle_id=vehicle.id,
                clip_id=clip.id,
                distance_feet=3.0,
                error_margin_feet=1.0,
                occurred_at=datetime.now(UTC),
            )
        )
        await session.commit()

    response = await admin_client.get("/api/ai/stats")
    assert response.json()["vehicle_proximity_breaches"] == 1


async def test_stats_counts_feedback_by_verdict(admin_client: AsyncClient, app: FastAPI) -> None:
    _camera, clip = await _make_camera_and_clip(app)
    analysis = await _make_analysis(app, clip)
    async with app.state.sessionmaker() as session:
        user = User(
            email=f"{uuid.uuid4()}@example.com",
            hashed_password="x",
            is_active=True,
            is_superuser=False,
            is_verified=True,
        )
        session.add(user)
        await session.flush()
        session.add(
            Feedback(analysis_id=analysis.id, user_id=user.id, verdict=FeedbackVerdict.CORRECT)
        )
        session.add(
            Feedback(
                analysis_id=analysis.id, user_id=user.id, verdict=FeedbackVerdict.FALSE_POSITIVE
            )
        )
        await session.commit()

    response = await admin_client.get("/api/ai/stats")
    body = response.json()
    assert body["total_feedback"] == 2
    assert body["correct_feedback"] == 1
    assert body["false_positive_feedback"] == 1
    assert body["false_negative_feedback"] == 0


async def test_viewer_can_read_stats(viewer_client: AsyncClient) -> None:
    assert (await viewer_client.get("/api/ai/stats")).status_code == 200


# --------------------------------------------------------------------- usage


async def test_usage_requires_authentication(client: AsyncClient) -> None:
    assert (await client.get("/api/ai/usage")).status_code == 401


async def test_usage_all_zero_with_no_data(admin_client: AsyncClient) -> None:
    response = await admin_client.get("/api/ai/usage")
    assert response.status_code == 200
    body = response.json()
    assert body["total_tokens"] == 0
    assert body["total_cost_usd"] == 0
    assert body["total_calls"] == 0
    assert body["daily"] == []
    assert body["by_provider"] == []


async def test_usage_aggregates_tokens_and_cost(admin_client: AsyncClient, app: FastAPI) -> None:
    _camera, clip = await _make_camera_and_clip(app)
    async with app.state.sessionmaker() as session:
        session.add(
            AIUsage(
                clip_id=clip.id,
                tier=AnalysisTier.TIER1,
                provider=AIProviderKind.OPENAI,
                model="gpt-5-nano",
                prompt_tokens=100,
                completion_tokens=20,
                total_tokens=120,
                estimated_cost_usd=0.05,
                latency_ms=500,
                success=True,
            )
        )
        session.add(
            AIUsage(
                clip_id=clip.id,
                tier=AnalysisTier.TIER1,
                provider=AIProviderKind.OPENAI,
                model="gpt-5-nano",
                success=False,
                error_message="boom",
            )
        )
        await session.commit()

    response = await admin_client.get("/api/ai/usage")
    body = response.json()
    assert body["total_tokens"] == 120
    assert body["total_calls"] == 2
    assert body["failed_calls"] == 1
    assert body["total_cost_usd"] == 0.05
    assert len(body["daily"]) == 1
    assert body["daily"][0]["tokens"] == 120
    assert len(body["by_provider"]) == 1
    assert body["by_provider"][0]["provider"] == "openai"
    assert body["by_provider"][0]["model"] == "gpt-5-nano"
    assert body["by_provider"][0]["calls"] == 2


async def test_usage_separates_by_provider_and_model(
    admin_client: AsyncClient, app: FastAPI
) -> None:
    _camera, clip = await _make_camera_and_clip(app)
    async with app.state.sessionmaker() as session:
        session.add(
            AIUsage(
                clip_id=clip.id,
                tier=AnalysisTier.TIER1,
                provider=AIProviderKind.OPENAI,
                model="gpt-5-nano",
                total_tokens=10,
                success=True,
            )
        )
        session.add(
            AIUsage(
                clip_id=clip.id,
                tier=AnalysisTier.TIER2,
                provider=AIProviderKind.ANTHROPIC,
                model="claude-sonnet-5",
                total_tokens=20,
                success=True,
            )
        )
        await session.commit()

    response = await admin_client.get("/api/ai/usage")
    providers = {row["provider"] for row in response.json()["by_provider"]}
    assert providers == {"openai", "anthropic"}
