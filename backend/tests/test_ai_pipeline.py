"""run_analysis: tier1 call, tier2 escalation, supersession, ai_usage
logging (including the durability of a failed call's row), and Event
creation. The provider itself is scripted/faked — never a real network
call, matching test_ai_providers.py's policy — but keyframe extraction
runs for real ffmpeg against a synthetic clip, matching
test_worker_download.py's "genuinely exercised" philosophy.
"""

# pytest calls autouse fixtures implicitly; pyright can't see that usage.
# pyright: reportUnusedFunction=false

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AIProviderKind, AISettings, AIUsage, Analysis, AnalysisTier, Event
from app.ai.pipeline import AnalysisSkippedError, run_analysis, suspicion_label_for
from app.ai.providers import AIProviderError, AnalysisRequest, AnalysisResult, DetectedEntityResult
from app.blink.models import BlinkAccount, Camera, Clip
from app.config import get_settings
from app.security.crypto import SecretBox
from app.vehicles.models import ProximityEvent, Vehicle


class ScriptedProvider:
    """Stands in for a real AIProvider: each call pops the next scripted
    result (or raises it, if it's an exception) off a shared queue."""

    queued: ClassVar[list[AnalysisResult | Exception]] = []
    calls: ClassVar[list[AnalysisRequest]] = []

    def __init__(self, model: str, api_key: str | None, base_url: str | None) -> None:
        del model, api_key, base_url

    async def analyze(self, request: AnalysisRequest) -> AnalysisResult:
        ScriptedProvider.calls.append(request)
        outcome = ScriptedProvider.queued.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def test_connection(self) -> None:  # pragma: no cover — unused by the pipeline
        pass


def _fake_build_provider(
    _kind: AIProviderKind, model: str, api_key: str | None, base_url: str | None
) -> ScriptedProvider:
    return ScriptedProvider(model, api_key, base_url)


@pytest.fixture(autouse=True)
def _reset_scripted_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    ScriptedProvider.queued = []
    ScriptedProvider.calls = []
    monkeypatch.setattr("app.ai.pipeline.build_provider", _fake_build_provider)


@pytest.fixture(scope="module")
def sample_clip_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("clips") / "sample.mp4"

    async def make() -> None:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=3:size=64x64:rate=10",
            "-pix_fmt",
            "yuv420p",
            str(path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate()

    asyncio.run(make())
    assert path.exists()
    return path


async def _make_camera_and_clip(
    session: AsyncSession,
    sample_clip_path: Path,
    *,
    security_context: str | None = None,
    downloaded: bool = True,
) -> tuple[Camera, Clip]:
    box = SecretBox(get_settings().encryption_key)
    account = BlinkAccount(
        encrypted_username=box.encrypt("a@example.com"),
        encrypted_password=box.encrypt("hunter2"),
        encrypted_token_data=box.encrypt("{}"),
    )
    session.add(account)
    await session.flush()

    camera = Camera(
        blink_account_id=account.id,
        blink_camera_id="cam-1",
        blink_network_id="net-1",
        name="Driveway",
        camera_type="catalina",
        security_context=security_context,
    )
    session.add(camera)
    await session.flush()

    clip = Clip(
        camera_id=camera.id,
        blink_clip_id="/media/clip1.mp4",
        recorded_at=datetime(2026, 7, 20, 14, 0, tzinfo=UTC),
        raw_metadata={},
        storage_path=str(sample_clip_path) if downloaded else None,
        downloaded_at=datetime.now(UTC) if downloaded else None,
    )
    session.add(clip)
    await session.commit()
    await session.refresh(camera)
    await session.refresh(clip)
    return camera, clip


VEHICLE_OUTLINE = [[0.3, 0.4], [0.7, 0.4], [0.7, 0.7], [0.3, 0.7]]
# 64x64 keyframes (testsrc never upscales): outline max span 25.6px, 15ft
# length -> ~1.707 px/ft; an average adult (5.6ft) measures ~0.149 normalized.
PERSON_HEIGHT = 0.14934


async def _make_vehicle(session: AsyncSession, camera: Camera, **overrides: object) -> Vehicle:
    defaults: dict[str, object] = {
        "camera_id": camera.id,
        "description": "The blue sedan",
        "outline_points": VEHICLE_OUTLINE,
    }
    defaults.update(overrides)
    vehicle = Vehicle(**defaults)  # type: ignore[arg-type]
    session.add(vehicle)
    await session.commit()
    await session.refresh(vehicle)
    return vehicle


def make_result(
    summary: str = "Nothing unusual.",
    suspicion: float = 0.1,
    entities: list[DetectedEntityResult] | None = None,
    input_tokens: int = 100,
    output_tokens: int = 20,
) -> AnalysisResult:
    return AnalysisResult(
        summary=summary,
        suspicion_score=suspicion,
        entities=entities or [],
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def make_settings(
    *,
    tier1_provider: AIProviderKind | None = AIProviderKind.OPENAI,
    tier1_model: str | None = "gpt-5-nano",
    tier2_enabled: bool = True,
    tier2_provider: AIProviderKind | None = AIProviderKind.ANTHROPIC,
    tier2_model: str | None = "claude-sonnet-5",
    tier2_suspicion_threshold: float = 0.5,
    keyframes_per_clip: int = 2,
) -> AISettings:
    return AISettings(
        tier1_provider=tier1_provider,
        tier1_model=tier1_model,
        tier2_enabled=tier2_enabled,
        tier2_provider=tier2_provider,
        tier2_model=tier2_model,
        tier2_suspicion_threshold=tier2_suspicion_threshold,
        keyframes_per_clip=keyframes_per_clip,
    )


def test_suspicion_label_thresholds() -> None:
    assert suspicion_label_for(0.0) == "routine"
    assert suspicion_label_for(0.29) == "routine"
    assert suspicion_label_for(0.3) == "uncertain"
    assert suspicion_label_for(0.59) == "uncertain"
    assert suspicion_label_for(0.6) == "suspicious"
    assert suspicion_label_for(1.0) == "suspicious"


async def test_raises_when_clip_not_downloaded(
    app_session: AsyncSession, sample_clip_path: Path
) -> None:
    camera, clip = await _make_camera_and_clip(app_session, sample_clip_path, downloaded=False)
    with pytest.raises(AnalysisSkippedError, match="not been downloaded"):
        await run_analysis(
            app_session, clip, camera, make_settings(), get_settings().encryption_key
        )


async def test_raises_when_tier1_not_configured(
    app_session: AsyncSession, sample_clip_path: Path
) -> None:
    camera, clip = await _make_camera_and_clip(app_session, sample_clip_path)
    settings = make_settings(tier1_provider=None, tier1_model=None)
    with pytest.raises(AnalysisSkippedError, match="Tier 1 provider is not configured"):
        await run_analysis(app_session, clip, camera, settings, get_settings().encryption_key)


async def test_persists_tier1_only_result_when_not_suspicious(
    app_session: AsyncSession, sample_clip_path: Path
) -> None:
    camera, clip = await _make_camera_and_clip(
        app_session, sample_clip_path, security_context="watches the driveway"
    )
    ScriptedProvider.queued = [make_result(summary="A car passes by.", suspicion=0.1)]
    settings = make_settings()

    analysis = await run_analysis(
        app_session, clip, camera, settings, get_settings().encryption_key
    )

    assert analysis.summary == "A car passes by."
    assert analysis.suspicion_label == "routine"
    assert analysis.tier == "tier1"
    assert analysis.escalated is False
    assert analysis.is_current is True
    assert len(ScriptedProvider.calls) == 1
    assert ScriptedProvider.calls[0].camera_context == "watches the driveway"

    usage_rows = (
        (await app_session.execute(select(AIUsage).where(AIUsage.clip_id == clip.id)))
        .scalars()
        .all()
    )
    assert len(usage_rows) == 1
    assert usage_rows[0].analysis_id == analysis.id
    assert usage_rows[0].success is True
    assert usage_rows[0].prompt_tokens == 100
    assert usage_rows[0].total_tokens == 120

    events = (
        (await app_session.execute(select(Event).where(Event.clip_id == clip.id))).scalars().all()
    )
    assert events == []  # nothing detected, nothing suspicious


async def test_escalates_to_tier2_when_tier1_is_suspicious(
    app_session: AsyncSession, sample_clip_path: Path
) -> None:
    camera, clip = await _make_camera_and_clip(app_session, sample_clip_path)
    ScriptedProvider.queued = [
        make_result(summary="Someone is lingering by the door.", suspicion=0.8),
        make_result(summary="Confirmed: a person is testing the door handle.", suspicion=0.9),
    ]
    settings = make_settings(tier2_suspicion_threshold=0.5)

    analysis = await run_analysis(
        app_session, clip, camera, settings, get_settings().encryption_key
    )

    assert analysis.summary == "Confirmed: a person is testing the door handle."
    assert analysis.tier == "tier2"
    assert analysis.escalated is True
    assert analysis.suspicion_label == "suspicious"
    assert len(ScriptedProvider.calls) == 2
    assert "preliminary suspicion" in (ScriptedProvider.calls[1].prior_tier_summary or "")

    usage_rows = (
        (await app_session.execute(select(AIUsage).where(AIUsage.clip_id == clip.id)))
        .scalars()
        .all()
    )
    assert {u.tier for u in usage_rows} == {"tier1", "tier2"}
    assert all(u.analysis_id == analysis.id for u in usage_rows)


async def test_does_not_escalate_when_tier2_disabled(
    app_session: AsyncSession, sample_clip_path: Path
) -> None:
    camera, clip = await _make_camera_and_clip(app_session, sample_clip_path)
    ScriptedProvider.queued = [make_result(suspicion=0.95)]
    settings = make_settings(tier2_enabled=False)

    analysis = await run_analysis(
        app_session, clip, camera, settings, get_settings().encryption_key
    )

    assert analysis.tier == "tier1"
    assert analysis.escalated is False
    assert len(ScriptedProvider.calls) == 1


async def test_does_not_escalate_when_tier2_unconfigured(
    app_session: AsyncSession, sample_clip_path: Path
) -> None:
    camera, clip = await _make_camera_and_clip(app_session, sample_clip_path)
    ScriptedProvider.queued = [make_result(suspicion=0.95)]
    settings = make_settings(tier2_provider=None, tier2_model=None)

    analysis = await run_analysis(
        app_session, clip, camera, settings, get_settings().encryption_key
    )

    assert analysis.tier == "tier1"
    assert analysis.escalated is False
    assert len(ScriptedProvider.calls) == 1


async def test_tier1_failure_raises_and_still_logs_ai_usage(
    app_session: AsyncSession, sample_clip_path: Path
) -> None:
    camera, clip = await _make_camera_and_clip(app_session, sample_clip_path)
    ScriptedProvider.queued = [AIProviderError("bad api key")]
    settings = make_settings()

    with pytest.raises(AnalysisSkippedError, match="Tier 1 analysis failed"):
        await run_analysis(app_session, clip, camera, settings, get_settings().encryption_key)

    usage_rows = (
        (await app_session.execute(select(AIUsage).where(AIUsage.clip_id == clip.id)))
        .scalars()
        .all()
    )
    assert len(usage_rows) == 1
    assert usage_rows[0].success is False
    assert usage_rows[0].error_message == "bad api key"
    assert usage_rows[0].analysis_id is None  # no Analysis exists to link to

    analyses = (
        (await app_session.execute(select(Analysis).where(Analysis.clip_id == clip.id)))
        .scalars()
        .all()
    )
    assert analyses == []


async def test_tier2_failure_falls_back_to_tier1_result(
    app_session: AsyncSession, sample_clip_path: Path
) -> None:
    camera, clip = await _make_camera_and_clip(app_session, sample_clip_path)
    ScriptedProvider.queued = [
        make_result(summary="Tier1 says suspicious.", suspicion=0.9),
        AIProviderError("tier2 rate limited"),
    ]
    settings = make_settings()

    analysis = await run_analysis(
        app_session, clip, camera, settings, get_settings().encryption_key
    )

    assert analysis.summary == "Tier1 says suspicious."
    assert analysis.tier == "tier1"
    assert analysis.escalated is False

    usage_rows = (
        (await app_session.execute(select(AIUsage).where(AIUsage.clip_id == clip.id)))
        .scalars()
        .all()
    )
    assert len(usage_rows) == 2
    by_tier = {u.tier: u for u in usage_rows}
    assert by_tier[AnalysisTier.TIER1].success is True
    assert by_tier[AnalysisTier.TIER2].success is False
    # The failed tier2 attempt is still linked to the analysis it fed into.
    assert by_tier[AnalysisTier.TIER1].analysis_id == analysis.id
    assert by_tier[AnalysisTier.TIER2].analysis_id == analysis.id


async def test_reanalyze_supersedes_the_prior_current_analysis(
    app_session: AsyncSession, sample_clip_path: Path
) -> None:
    camera, clip = await _make_camera_and_clip(app_session, sample_clip_path)
    settings = make_settings()

    ScriptedProvider.queued = [make_result(summary="First pass.", suspicion=0.1)]
    first = await run_analysis(app_session, clip, camera, settings, get_settings().encryption_key)

    ScriptedProvider.queued = [make_result(summary="Second pass.", suspicion=0.1)]
    second = await run_analysis(app_session, clip, camera, settings, get_settings().encryption_key)

    await app_session.refresh(first)
    assert first.is_current is False
    assert first.superseded_at is not None
    assert second.is_current is True
    assert second.summary == "Second pass."

    current = (
        await app_session.execute(
            select(Analysis).where(Analysis.clip_id == clip.id, Analysis.is_current.is_(True))
        )
    ).scalar_one()
    assert current.id == second.id


async def test_writes_events_for_detected_entities(
    app_session: AsyncSession, sample_clip_path: Path
) -> None:
    camera, clip = await _make_camera_and_clip(app_session, sample_clip_path)
    ScriptedProvider.queued = [
        make_result(
            suspicion=0.1,
            entities=[
                DetectedEntityResult(type="person", confidence=0.9, label="delivery driver"),
                DetectedEntityResult(type="vehicle", confidence=0.7, label="van"),
            ],
        )
    ]
    settings = make_settings()

    analysis = await run_analysis(
        app_session, clip, camera, settings, get_settings().encryption_key
    )

    events = (
        (await app_session.execute(select(Event).where(Event.clip_id == clip.id))).scalars().all()
    )
    event_types = {e.event_type for e in events}
    assert event_types == {"person_detected", "vehicle_detected"}
    for event in events:
        assert event.analysis_id == analysis.id
        assert event.camera_id == camera.id


async def test_writes_suspicious_activity_event_when_suspicious(
    app_session: AsyncSession, sample_clip_path: Path
) -> None:
    camera, clip = await _make_camera_and_clip(app_session, sample_clip_path)
    ScriptedProvider.queued = [make_result(suspicion=0.95)]
    settings = make_settings(tier2_enabled=False)

    await run_analysis(app_session, clip, camera, settings, get_settings().encryption_key)

    events = (
        (await app_session.execute(select(Event).where(Event.clip_id == clip.id))).scalars().all()
    )
    assert len(events) == 1
    assert events[0].event_type == "suspicious_activity"
    assert events[0].confidence == 0.95


async def test_unknown_entity_type_maps_to_unknown_detected(
    app_session: AsyncSession, sample_clip_path: Path
) -> None:
    camera, clip = await _make_camera_and_clip(app_session, sample_clip_path)
    ScriptedProvider.queued = [
        make_result(
            suspicion=0.1,
            entities=[DetectedEntityResult(type="unknown", confidence=0.4, label="something")],
        )
    ]
    settings = make_settings(tier2_enabled=False)

    await run_analysis(app_session, clip, camera, settings, get_settings().encryption_key)

    events = (
        (await app_session.execute(select(Event).where(Event.clip_id == clip.id))).scalars().all()
    )
    assert len(events) == 1
    assert events[0].event_type == "unknown_detected"


async def test_reanalyze_updates_existing_event_rows_instead_of_duplicating(
    app_session: AsyncSession, sample_clip_path: Path
) -> None:
    camera, clip = await _make_camera_and_clip(app_session, sample_clip_path)
    settings = make_settings(tier2_enabled=False)

    ScriptedProvider.queued = [
        make_result(
            suspicion=0.1,
            entities=[DetectedEntityResult(type="person", confidence=0.5, label="someone")],
        )
    ]
    await run_analysis(app_session, clip, camera, settings, get_settings().encryption_key)

    ScriptedProvider.queued = [
        make_result(
            suspicion=0.1,
            entities=[DetectedEntityResult(type="person", confidence=0.99, label="known face")],
        )
    ]
    second = await run_analysis(app_session, clip, camera, settings, get_settings().encryption_key)

    events = (
        (
            await app_session.execute(
                select(Event).where(Event.clip_id == clip.id, Event.event_type == "person_detected")
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 1  # updated in place, not duplicated
    assert events[0].confidence == 0.99
    assert events[0].analysis_id == second.id


async def test_no_keyframes_extracted_raises_analysis_skipped(
    app_session: AsyncSession, sample_clip_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    camera, clip = await _make_camera_and_clip(app_session, sample_clip_path)
    settings = make_settings()

    async def fake_extract(*_args: object, **_kwargs: object) -> list[bytes]:
        return []

    monkeypatch.setattr("app.ai.pipeline.extract_keyframes", fake_extract)
    with pytest.raises(AnalysisSkippedError, match="Could not extract any keyframes"):
        await run_analysis(app_session, clip, camera, settings, get_settings().encryption_key)


# ------------------------------------------------------------ vehicle proximity


async def test_no_vehicle_proximity_field_when_no_vehicle_registered(
    app_session: AsyncSession, sample_clip_path: Path
) -> None:
    camera, clip = await _make_camera_and_clip(app_session, sample_clip_path)
    ScriptedProvider.queued = [
        make_result(
            entities=[
                DetectedEntityResult(
                    type="person", confidence=0.9, label="someone", bbox=(0.5, 0.5, 0.1, 0.1)
                )
            ]
        )
    ]
    analysis = await run_analysis(
        app_session, clip, camera, make_settings(tier2_enabled=False), get_settings().encryption_key
    )
    assert analysis.vehicle_proximity is None
    assert ScriptedProvider.calls[0].detect_people_for_proximity is False


async def test_vehicle_registered_requests_proximity_bboxes(
    app_session: AsyncSession, sample_clip_path: Path
) -> None:
    camera, clip = await _make_camera_and_clip(app_session, sample_clip_path)
    await _make_vehicle(app_session, camera)
    ScriptedProvider.queued = [make_result()]
    await run_analysis(
        app_session, clip, camera, make_settings(tier2_enabled=False), get_settings().encryption_key
    )
    assert ScriptedProvider.calls[0].detect_people_for_proximity is True


async def test_close_person_breaches_the_threshold(
    app_session: AsyncSession, sample_clip_path: Path
) -> None:
    camera, clip = await _make_camera_and_clip(app_session, sample_clip_path)
    await _make_vehicle(app_session, camera)
    close_bbox = (0.71, 0.55 - PERSON_HEIGHT, 0.02, PERSON_HEIGHT)
    ScriptedProvider.queued = [
        make_result(
            entities=[
                DetectedEntityResult(
                    type="person", confidence=0.9, label="someone", bbox=close_bbox
                )
            ]
        )
    ]
    analysis = await run_analysis(
        app_session, clip, camera, make_settings(tier2_enabled=False), get_settings().encryption_key
    )

    assert analysis.vehicle_proximity is not None
    assert analysis.vehicle_proximity["breached_threshold"] is True
    assert analysis.vehicle_proximity["distance_feet"] < 2.0

    proximity_events = (await app_session.execute(select(ProximityEvent))).scalars().all()
    assert len(proximity_events) == 1
    assert proximity_events[0].clip_id == clip.id

    breach_event = (
        await app_session.execute(
            select(Event).where(
                Event.clip_id == clip.id, Event.event_type == "vehicle_proximity_breach"
            )
        )
    ).scalar_one()
    assert breach_event.analysis_id == analysis.id


async def test_far_person_at_the_same_depth_does_not_breach(
    app_session: AsyncSession, sample_clip_path: Path
) -> None:
    camera, clip = await _make_camera_and_clip(app_session, sample_clip_path)
    await _make_vehicle(app_session, camera)
    far_bbox = (0.04, 0.55 - PERSON_HEIGHT, 0.02, PERSON_HEIGHT)
    ScriptedProvider.queued = [
        make_result(
            entities=[
                DetectedEntityResult(type="person", confidence=0.9, label="someone", bbox=far_bbox)
            ]
        )
    ]
    analysis = await run_analysis(
        app_session, clip, camera, make_settings(tier2_enabled=False), get_settings().encryption_key
    )

    assert analysis.vehicle_proximity is not None
    assert analysis.vehicle_proximity["breached_threshold"] is False

    proximity_events = (await app_session.execute(select(ProximityEvent))).scalars().all()
    assert proximity_events == []


async def test_person_at_a_different_depth_yields_no_proximity_estimate(
    app_session: AsyncSession, sample_clip_path: Path
) -> None:
    camera, clip = await _make_camera_and_clip(app_session, sample_clip_path)
    await _make_vehicle(app_session, camera)
    # Much shorter than an average adult would measure at the vehicle's
    # depth -> plausibly far behind it, not physically nearby.
    distant_bbox = (0.49, 0.47, 0.02, 0.03)
    ScriptedProvider.queued = [
        make_result(
            entities=[
                DetectedEntityResult(
                    type="person", confidence=0.9, label="someone", bbox=distant_bbox
                )
            ]
        )
    ]
    analysis = await run_analysis(
        app_session, clip, camera, make_settings(tier2_enabled=False), get_settings().encryption_key
    )
    assert analysis.vehicle_proximity is None


async def test_picks_the_closest_of_multiple_people(
    app_session: AsyncSession, sample_clip_path: Path
) -> None:
    camera, clip = await _make_camera_and_clip(app_session, sample_clip_path)
    await _make_vehicle(app_session, camera)
    close_bbox = (0.71, 0.55 - PERSON_HEIGHT, 0.02, PERSON_HEIGHT)
    far_bbox = (0.04, 0.55 - PERSON_HEIGHT, 0.02, PERSON_HEIGHT)
    ScriptedProvider.queued = [
        make_result(
            entities=[
                DetectedEntityResult(type="person", confidence=0.9, label="far one", bbox=far_bbox),
                DetectedEntityResult(
                    type="person", confidence=0.9, label="close one", bbox=close_bbox
                ),
            ]
        )
    ]
    analysis = await run_analysis(
        app_session, clip, camera, make_settings(tier2_enabled=False), get_settings().encryption_key
    )
    assert analysis.vehicle_proximity is not None
    assert analysis.vehicle_proximity["breached_threshold"] is True


async def test_disabled_vehicle_is_treated_as_unregistered(
    app_session: AsyncSession, sample_clip_path: Path
) -> None:
    camera, clip = await _make_camera_and_clip(app_session, sample_clip_path)
    await _make_vehicle(app_session, camera, enabled=False)
    ScriptedProvider.queued = [make_result()]
    analysis = await run_analysis(
        app_session, clip, camera, make_settings(tier2_enabled=False), get_settings().encryption_key
    )
    assert analysis.vehicle_proximity is None
    assert ScriptedProvider.calls[0].detect_people_for_proximity is False


async def test_vehicle_with_incomplete_outline_is_treated_as_unregistered(
    app_session: AsyncSession, sample_clip_path: Path
) -> None:
    camera, clip = await _make_camera_and_clip(app_session, sample_clip_path)
    await _make_vehicle(app_session, camera, outline_points=[[0.3, 0.4], [0.7, 0.4]])
    ScriptedProvider.queued = [make_result()]
    analysis = await run_analysis(
        app_session, clip, camera, make_settings(tier2_enabled=False), get_settings().encryption_key
    )
    assert analysis.vehicle_proximity is None
    assert ScriptedProvider.calls[0].detect_people_for_proximity is False


async def test_no_people_detected_leaves_proximity_null(
    app_session: AsyncSession, sample_clip_path: Path
) -> None:
    camera, clip = await _make_camera_and_clip(app_session, sample_clip_path)
    await _make_vehicle(app_session, camera)
    ScriptedProvider.queued = [make_result(entities=[])]
    analysis = await run_analysis(
        app_session, clip, camera, make_settings(tier2_enabled=False), get_settings().encryption_key
    )
    assert analysis.vehicle_proximity is None
