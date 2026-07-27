"""analyze_clip: the arq task wrapper around run_analysis — missing clip,
AI-disabled short-circuit, and the happy path. run_analysis's own branch
coverage (escalation, supersession, event writes, failure handling) lives
in test_ai_pipeline.py; this file only covers the task-level plumbing.
"""

# pytest calls autouse fixtures implicitly; pyright can't see that usage.
# pyright: reportUnusedFunction=false

import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.learning import update_baseline
from app.ai.models import AIProviderKind, CameraBaseline
from app.ai.providers import AnalysisRequest, AnalysisResult, DetectedEntityResult
from app.ai.schemas import AISettingsUpdate
from app.ai.service import get_ai_settings, update_ai_settings
from app.alerts.schemas import AlertSettingsUpdate
from app.alerts.service import update_alert_settings
from app.blink.models import BlinkAccount, Camera, Clip, StorageBackend
from app.config import get_settings
from app.integrations.schemas import StorageIntegrationSettingsUpdate
from app.integrations.service import update_storage_integration_settings
from app.security.crypto import SecretBox
from app.vehicles.models import Vehicle
from app.worker.tasks.alerts import SEND_ALERT_JOB_NAME
from app.worker.tasks.analyze import analyze_clip
from app.worker.tasks.archive import ARCHIVE_CLIP_JOB_NAME

VEHICLE_OUTLINE = [[0.3, 0.4], [0.7, 0.4], [0.7, 0.7], [0.3, 0.7]]
# Same 64x64-frame geometry as test_ai_pipeline.py: outline max span
# 25.6px, 15ft length -> ~1.707 px/ft; average adult measures ~0.149 tall.
PERSON_HEIGHT = 0.14934


class ScriptedProvider:
    queued: ClassVar[list[AnalysisResult]] = []
    calls: ClassVar[list[AnalysisRequest]] = []

    def __init__(self, model: str, api_key: str | None, base_url: str | None) -> None:
        del model, api_key, base_url

    async def analyze(self, request: AnalysisRequest) -> AnalysisResult:
        ScriptedProvider.calls.append(request)
        return ScriptedProvider.queued.pop(0)

    async def test_connection(self) -> None:  # pragma: no cover — unused here
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
    session: AsyncSession, sample_clip_path: Path, *, downloaded: bool = True, enabled: bool = True
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
        enabled=enabled,
    )
    session.add(camera)
    await session.flush()

    clip = Clip(
        camera_id=camera.id,
        blink_clip_id="/media/clip1.mp4",
        recorded_at=datetime(2026, 7, 20, tzinfo=UTC),
        raw_metadata={},
        storage_path=str(sample_clip_path) if downloaded else None,
        downloaded_at=datetime.now(UTC) if downloaded else None,
    )
    session.add(clip)
    await session.commit()
    await session.refresh(camera)
    await session.refresh(clip)
    return camera, clip


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
    return vehicle


async def test_clip_not_found_is_a_clean_noop(worker_ctx: dict[str, Any]) -> None:
    result = await analyze_clip(worker_ctx, str(uuid.uuid4()))
    assert result == "clip_not_found"


async def test_ai_disabled_short_circuits(
    worker_ctx: dict[str, Any], sample_clip_path: Path
) -> None:
    async with worker_ctx["sessionmaker"]() as session:
        _camera, clip = await _make_camera_and_clip(session, sample_clip_path)
        clip_id = clip.id

    result = await analyze_clip(worker_ctx, str(clip_id))
    assert result == "ai_disabled"


async def test_auto_archive_is_enqueued_regardless_of_analysis_outcome(
    worker_ctx: dict[str, Any], sample_clip_path: Path
) -> None:
    async with worker_ctx["sessionmaker"]() as session:
        _camera, clip = await _make_camera_and_clip(session, sample_clip_path)
        clip_id = clip.id
        await update_storage_integration_settings(
            session,
            StorageIntegrationSettingsUpdate(auto_archive_backend=StorageBackend.S3),
            get_settings().encryption_key,
        )

    result = await analyze_clip(worker_ctx, str(clip_id))
    assert result == "ai_disabled"
    worker_ctx["redis"].enqueue_job.assert_awaited_once_with(
        ARCHIVE_CLIP_JOB_NAME, clip_id=str(clip_id), backend="s3"
    )


async def test_auto_archive_is_not_enqueued_when_left_local(
    worker_ctx: dict[str, Any], sample_clip_path: Path
) -> None:
    async with worker_ctx["sessionmaker"]() as session:
        _camera, clip = await _make_camera_and_clip(session, sample_clip_path)
        clip_id = clip.id

    await analyze_clip(worker_ctx, str(clip_id))
    worker_ctx["redis"].enqueue_job.assert_not_awaited()


async def test_camera_disabled_short_circuits(
    worker_ctx: dict[str, Any], sample_clip_path: Path
) -> None:
    # Defense in depth: the API layer already refuses to enqueue analysis for
    # a disabled camera's clips, but a job already sitting in the queue when
    # the camera gets disabled must still no-op cleanly rather than analyze.
    async with worker_ctx["sessionmaker"]() as session:
        _camera, clip = await _make_camera_and_clip(session, sample_clip_path, enabled=False)
        clip_id = clip.id
        await update_ai_settings(
            session,
            AISettingsUpdate(
                enabled=True, tier1_provider=AIProviderKind.OPENAI, tier1_model="gpt-5-nano"
            ),
            get_settings().encryption_key,
        )

    result = await analyze_clip(worker_ctx, str(clip_id))
    assert result == "camera_disabled"


async def test_skipped_when_clip_not_downloaded(
    worker_ctx: dict[str, Any], sample_clip_path: Path
) -> None:
    async with worker_ctx["sessionmaker"]() as session:
        _camera, clip = await _make_camera_and_clip(session, sample_clip_path, downloaded=False)
        clip_id = clip.id
        await update_ai_settings(
            session,
            AISettingsUpdate(
                enabled=True, tier1_provider=AIProviderKind.OPENAI, tier1_model="gpt-5-nano"
            ),
            get_settings().encryption_key,
        )

    result = await analyze_clip(worker_ctx, str(clip_id))
    assert result == "skipped"


async def test_successful_analysis_returns_ok(
    worker_ctx: dict[str, Any], sample_clip_path: Path
) -> None:
    async with worker_ctx["sessionmaker"]() as session:
        _camera, clip = await _make_camera_and_clip(session, sample_clip_path)
        clip_id = clip.id
        await update_ai_settings(
            session,
            AISettingsUpdate(
                enabled=True,
                tier1_provider=AIProviderKind.OPENAI,
                tier1_model="gpt-5-nano",
                tier2_enabled=False,
            ),
            get_settings().encryption_key,
        )

    ScriptedProvider.queued = [
        AnalysisResult(
            summary="A car passes by.",
            suspicion_score=0.1,
            entities=[],
            input_tokens=50,
            output_tokens=10,
        )
    ]
    result = await analyze_clip(worker_ctx, str(clip_id))
    assert result == "ok"

    async with worker_ctx["sessionmaker"]() as session:
        settings = await get_ai_settings(session)
        assert settings.enabled is True  # sanity: settings persisted across sessions


async def test_successful_analysis_updates_the_camera_baseline(
    worker_ctx: dict[str, Any], sample_clip_path: Path
) -> None:
    async with worker_ctx["sessionmaker"]() as session:
        camera, clip = await _make_camera_and_clip(session, sample_clip_path)
        camera_id, clip_id, recorded_hour = camera.id, clip.id, clip.recorded_at.hour
        await update_ai_settings(
            session,
            AISettingsUpdate(
                enabled=True,
                tier1_provider=AIProviderKind.OPENAI,
                tier1_model="gpt-5-nano",
                tier2_enabled=False,
            ),
            get_settings().encryption_key,
        )

    ScriptedProvider.queued = [
        AnalysisResult(
            summary="A person walks by.",
            suspicion_score=0.1,
            entities=[DetectedEntityResult(type="person", confidence=0.9, label="someone")],
            input_tokens=50,
            output_tokens=10,
        )
    ]
    result = await analyze_clip(worker_ctx, str(clip_id))
    assert result == "ok"

    async with worker_ctx["sessionmaker"]() as session:
        baseline = (
            await session.execute(
                select(CameraBaseline).where(CameraBaseline.camera_id == camera_id)
            )
        ).scalar_one()
        assert baseline.hourly_entity_counts == {str(recorded_hour): {"person": 1}}
        assert baseline.total_observations == 1


async def test_analysis_is_conditioned_on_existing_baseline_and_feedback(
    worker_ctx: dict[str, Any], sample_clip_path: Path
) -> None:
    async with worker_ctx["sessionmaker"]() as session:
        camera, clip = await _make_camera_and_clip(session, sample_clip_path)
        clip_id = clip.id
        await update_baseline(session, camera.id, clip.recorded_at, ["person", "person", "person"])
        await session.commit()
        await update_ai_settings(
            session,
            AISettingsUpdate(
                enabled=True,
                tier1_provider=AIProviderKind.OPENAI,
                tier1_model="gpt-5-nano",
                tier2_enabled=False,
            ),
            get_settings().encryption_key,
        )

    ScriptedProvider.queued = [
        AnalysisResult(
            summary="A person walks by.",
            suspicion_score=0.1,
            entities=[],
            input_tokens=50,
            output_tokens=10,
        )
    ]
    result = await analyze_clip(worker_ctx, str(clip_id))
    assert result == "ok"

    assert len(ScriptedProvider.calls) == 1
    assert ScriptedProvider.calls[0].baseline_context is not None
    assert "person" in ScriptedProvider.calls[0].baseline_context


# ------------------------------------------------------------- alert triggers


async def test_suspicious_analysis_enqueues_an_alert(
    worker_ctx: dict[str, Any], sample_clip_path: Path
) -> None:
    async with worker_ctx["sessionmaker"]() as session:
        camera, clip = await _make_camera_and_clip(session, sample_clip_path)
        camera_id, clip_id = camera.id, clip.id
        await update_ai_settings(
            session,
            AISettingsUpdate(
                enabled=True,
                tier1_provider=AIProviderKind.OPENAI,
                tier1_model="gpt-5-nano",
                tier2_enabled=False,
            ),
            get_settings().encryption_key,
        )

    ScriptedProvider.queued = [
        AnalysisResult(
            summary="Someone is prying at the window.",
            suspicion_score=0.9,
            entities=[],
            input_tokens=50,
            output_tokens=10,
        )
    ]
    result = await analyze_clip(worker_ctx, str(clip_id))
    assert result == "ok"

    worker_ctx["redis"].enqueue_job.assert_awaited_once()
    call = worker_ctx["redis"].enqueue_job.await_args
    assert call.args == (SEND_ALERT_JOB_NAME,)
    assert call.kwargs["camera_id"] == str(camera_id)
    assert call.kwargs["reason"] == "suspicious_activity"
    assert "Someone is prying" in call.kwargs["message"]


async def test_routine_analysis_does_not_enqueue_an_alert(
    worker_ctx: dict[str, Any], sample_clip_path: Path
) -> None:
    async with worker_ctx["sessionmaker"]() as session:
        _camera, clip = await _make_camera_and_clip(session, sample_clip_path)
        clip_id = clip.id
        await update_ai_settings(
            session,
            AISettingsUpdate(
                enabled=True,
                tier1_provider=AIProviderKind.OPENAI,
                tier1_model="gpt-5-nano",
                tier2_enabled=False,
            ),
            get_settings().encryption_key,
        )

    ScriptedProvider.queued = [
        AnalysisResult(
            summary="Nothing unusual.",
            suspicion_score=0.1,
            entities=[],
            input_tokens=50,
            output_tokens=10,
        )
    ]
    result = await analyze_clip(worker_ctx, str(clip_id))
    assert result == "ok"
    worker_ctx["redis"].enqueue_job.assert_not_awaited()


async def test_alert_on_suspicious_disabled_skips_the_alert(
    worker_ctx: dict[str, Any], sample_clip_path: Path
) -> None:
    async with worker_ctx["sessionmaker"]() as session:
        _camera, clip = await _make_camera_and_clip(session, sample_clip_path)
        clip_id = clip.id
        await update_ai_settings(
            session,
            AISettingsUpdate(
                enabled=True,
                tier1_provider=AIProviderKind.OPENAI,
                tier1_model="gpt-5-nano",
                tier2_enabled=False,
            ),
            get_settings().encryption_key,
        )
        await update_alert_settings(
            session,
            AlertSettingsUpdate(alert_on_suspicious_clip=False),
            get_settings().encryption_key,
        )

    ScriptedProvider.queued = [
        AnalysisResult(
            summary="Someone is prying at the window.",
            suspicion_score=0.9,
            entities=[],
            input_tokens=50,
            output_tokens=10,
        )
    ]
    result = await analyze_clip(worker_ctx, str(clip_id))
    assert result == "ok"
    worker_ctx["redis"].enqueue_job.assert_not_awaited()


async def test_vehicle_proximity_breach_enqueues_an_alert(
    worker_ctx: dict[str, Any], sample_clip_path: Path
) -> None:
    async with worker_ctx["sessionmaker"]() as session:
        camera, clip = await _make_camera_and_clip(session, sample_clip_path)
        camera_id, clip_id = camera.id, clip.id
        await _make_vehicle(session, camera)
        await update_ai_settings(
            session,
            AISettingsUpdate(
                enabled=True,
                tier1_provider=AIProviderKind.OPENAI,
                tier1_model="gpt-5-nano",
                tier2_enabled=False,
            ),
            get_settings().encryption_key,
        )

    close_bbox = (0.71, 0.55 - PERSON_HEIGHT, 0.02, PERSON_HEIGHT)
    ScriptedProvider.queued = [
        AnalysisResult(
            summary="A person is at the car.",
            suspicion_score=0.1,
            entities=[
                DetectedEntityResult(
                    type="person", confidence=0.9, label="someone", bbox=close_bbox
                )
            ],
            input_tokens=50,
            output_tokens=10,
        )
    ]
    result = await analyze_clip(worker_ctx, str(clip_id))
    assert result == "ok"

    worker_ctx["redis"].enqueue_job.assert_awaited_once()
    call = worker_ctx["redis"].enqueue_job.await_args
    assert call.args == (SEND_ALERT_JOB_NAME,)
    assert call.kwargs["camera_id"] == str(camera_id)
    assert call.kwargs["reason"] == "vehicle_proximity"
    assert "from your vehicle" in call.kwargs["message"]
