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
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AIProviderKind
from app.ai.providers import AnalysisRequest, AnalysisResult
from app.ai.schemas import AISettingsUpdate
from app.ai.service import get_ai_settings, update_ai_settings
from app.blink.models import BlinkAccount, Camera, Clip
from app.config import get_settings
from app.security.crypto import SecretBox
from app.worker.tasks.analyze import analyze_clip


class ScriptedProvider:
    queued: ClassVar[list[AnalysisResult]] = []

    def __init__(self, model: str, api_key: str | None, base_url: str | None) -> None:
        del model, api_key, base_url

    async def analyze(self, request: AnalysisRequest) -> AnalysisResult:
        del request
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
    session: AsyncSession, sample_clip_path: Path, *, downloaded: bool = True
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
