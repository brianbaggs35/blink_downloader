"""e2e fixture seeding is idempotent and produces a usable admin + demo data."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

import app.testing.seed as seed_module
from app.ai.models import AIUsage
from app.biometrics.models import Person
from app.biometrics.recognition import ModelLoadError
from app.blink.models import Camera, Clip
from app.settings.service import set_storage_dir
from app.testing.seed import DEMO_PERSON_NAME, E2E_ADMIN_EMAIL, E2E_ADMIN_PASSWORD, seed
from app.vehicles.models import ProximityEvent, Vehicle
from tests.conftest import login


async def test_seed_creates_admin_once(client: AsyncClient, app: FastAPI, tmp_path: Path) -> None:
    async with app.state.sessionmaker() as session:
        await set_storage_dir(session, str(tmp_path))

    assert await seed() is True
    assert await seed() is False  # idempotent

    await login(client, E2E_ADMIN_EMAIL, E2E_ADMIN_PASSWORD)
    me = await client.get("/api/users/me")
    assert me.status_code == 200
    assert me.json()["is_superuser"] is True

    async with app.state.sessionmaker() as session:
        clips = (await session.execute(select(Clip))).scalars().all()
        assert len(clips) == 16
        downloaded = [c for c in clips if c.downloaded_at is not None]
        assert len(downloaded) == 15
        for clip in downloaded:
            assert clip.storage_path is not None
            assert Path(clip.storage_path).exists()

        person = (
            await session.execute(select(Person).where(Person.name == DEMO_PERSON_NAME))
        ).scalar_one()
        assert person.thumbnail_path is not None
        assert Path(person.thumbnail_path).exists()

        cameras = (await session.execute(select(Camera))).scalars().all()
        assert len(cameras) == 2
        for camera in cameras:
            assert camera.preview_path is not None
            assert camera.preview_updated_at is not None
            assert Path(camera.preview_path).exists()

        vehicle = (await session.execute(select(Vehicle))).scalar_one()
        assert vehicle.reference_frame_path is not None
        assert Path(vehicle.reference_frame_path).exists()
        assert len(vehicle.outline_points) >= 3

        proximity_events = (await session.execute(select(ProximityEvent))).scalars().all()
        assert len(proximity_events) == 3
        assert all(event.vehicle_id == vehicle.id for event in proximity_events)

        usage_rows = (await session.execute(select(AIUsage))).scalars().all()
        assert len(usage_rows) == 6
        assert sum(1 for row in usage_rows if not row.success) == 1
        assert len({row.provider for row in usage_rows}) == 2

    # Leave a clean slate for other tests (client fixture truncates pre-test too).
    async with app.state.sessionmaker() as session:
        await session.execute(
            text(
                "TRUNCATE TABLE access_tokens, users, blink_accounts, people, analyses, "
                "vehicles, ai_usage CASCADE"
            )
        )
        await session.commit()


async def test_warm_up_biometrics_model_logs_success_when_the_model_loads(
    app_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_verify_model(*_args: object, **_kwargs: object) -> list[str]:
        return ["CPUExecutionProvider"]

    monkeypatch.setattr(seed_module, "verify_model", _fake_verify_model)
    await seed_module.warm_up_biometrics_model()  # must not raise


async def test_warm_up_biometrics_model_swallows_a_load_failure(
    app_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _boom(*_args: object, **_kwargs: object) -> list[str]:
        raise ModelLoadError("could not download the model")

    monkeypatch.setattr(seed_module, "verify_model", _boom)
    await seed_module.warm_up_biometrics_model()  # must not raise
