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
from app.blink.models import BatteryEvent, Camera, Clip
from app.settings.service import set_storage_dir
from app.sync_module.models import LocalItemStatus, SyncModule, SyncModuleLocalItem
from app.testing.seed import (
    DEMO_PERSON_NAME,
    E2E_ADMIN_EMAIL,
    E2E_ADMIN_PASSWORD,
    E2E_VIEWER_EMAIL,
    E2E_VIEWER_PASSWORD,
    reset_data,
    seed,
    seed_data,
    seed_identity,
)
from app.users.models import User
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

    await client.post("/api/auth/logout")
    await login(client, E2E_VIEWER_EMAIL, E2E_VIEWER_PASSWORD)
    viewer_me = await client.get("/api/users/me")
    assert viewer_me.status_code == 200
    assert viewer_me.json()["is_superuser"] is False

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
        cameras_by_name = {camera.name: camera for camera in cameras}
        assert cameras_by_name["Front Door"].battery == "ok"
        assert cameras_by_name["Backyard"].battery == "low"

        battery_events = (await session.execute(select(BatteryEvent))).scalars().all()
        by_camera: dict[str, list[BatteryEvent]] = {"Front Door": [], "Backyard": []}
        for event in battery_events:
            name = next(c.name for c in cameras if c.id == event.camera_id)
            by_camera[name].append(event)
        assert len(by_camera["Front Door"]) == 1  # sparse history
        assert len(by_camera["Backyard"]) == 2  # richer: an ok -> low transition

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

        sync_module = (await session.execute(select(SyncModule))).scalar_one()
        assert sync_module.is_physical_hub is True
        assert sync_module.armed is True
        assert sync_module.online is True
        assert sync_module.local_storage_compatible is True
        assert sync_module.local_storage_enabled is True
        assert sync_module.local_storage_active is True

        local_items = (await session.execute(select(SyncModuleLocalItem))).scalars().all()
        assert len(local_items) == 3
        by_status = {item.status: item for item in local_items}
        assert set(by_status) == {
            LocalItemStatus.AVAILABLE,
            LocalItemStatus.DOWNLOADED,
            LocalItemStatus.ERROR,
        }
        downloaded_item = by_status[LocalItemStatus.DOWNLOADED]
        assert downloaded_item.storage_path is not None
        assert Path(downloaded_item.storage_path).exists()
        assert by_status[LocalItemStatus.ERROR].last_error is not None

    # Leave a clean slate for other tests (client fixture truncates pre-test too).
    async with app.state.sessionmaker() as session:
        await session.execute(
            text(
                "TRUNCATE TABLE access_tokens, users, blink_accounts, people, analyses, "
                "vehicles, ai_usage CASCADE"
            )
        )
        await session.commit()


async def test_seed_identity_creates_admin_and_viewer_once(app_session: AsyncSession) -> None:
    assert await seed_identity(app_session) is True
    assert await seed_identity(app_session) is False  # idempotent, no duplicates

    users = (await app_session.execute(select(User))).scalars().all()
    assert len(users) == 2
    by_email = {user.email: user for user in users}
    assert by_email[E2E_ADMIN_EMAIL].is_superuser is True
    assert by_email[E2E_VIEWER_EMAIL].is_superuser is False


async def test_reset_data_preserves_identity_and_replaces_domain_data(
    app_session: AsyncSession, tmp_path: Path
) -> None:
    await set_storage_dir(app_session, str(tmp_path))
    await seed_identity(app_session)
    await seed_data(app_session)

    admin_before = (
        await app_session.execute(
            select(User).where(User.email == E2E_ADMIN_EMAIL)  # pyright: ignore[reportArgumentType]
        )
    ).scalar_one()
    camera_before = (
        await app_session.execute(select(Camera).where(Camera.name == "Backyard"))
    ).scalar_one()
    # Mutate exactly like a real test would (e.g. toggling a camera off) -
    # the reset should undo this, not just leave the row count unchanged.
    camera_before.enabled = False
    await app_session.commit()

    await reset_data(app_session)

    admin_after = (
        await app_session.execute(
            select(User).where(User.email == E2E_ADMIN_EMAIL)  # pyright: ignore[reportArgumentType]
        )
    ).scalar_one()
    assert admin_after.id == admin_before.id  # same identity row, not recreated

    camera_after = (
        await app_session.execute(select(Camera).where(Camera.name == "Backyard"))
    ).scalar_one()
    assert camera_after.id == camera_before.id  # same deterministic fixture id
    assert camera_after.enabled is True  # back to the seeded baseline

    clips = (await app_session.execute(select(Clip))).scalars().all()
    assert len(clips) == 16  # the full fixture set, not left empty or duplicated


async def test_reset_data_is_repeatable(app_session: AsyncSession, tmp_path: Path) -> None:
    await set_storage_dir(app_session, str(tmp_path))
    await seed_identity(app_session)
    await seed_data(app_session)

    await reset_data(app_session)
    await reset_data(app_session)  # must not raise (duplicate-key, etc.)

    clips = (await app_session.execute(select(Clip))).scalars().all()
    assert len(clips) == 16


async def test_warm_up_biometrics_model_logs_success_when_the_model_loads(
    app_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_download_biometrics_model(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(seed_module, "download_biometrics_model", _fake_download_biometrics_model)
    await seed_module.warm_up_biometrics_model()  # must not raise


async def test_warm_up_biometrics_model_swallows_a_load_failure(
    app_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _boom(*_args: object, **_kwargs: object) -> None:
        raise ModelLoadError("could not download the model")

    monkeypatch.setattr(seed_module, "download_biometrics_model", _boom)
    await seed_module.warm_up_biometrics_model()  # must not raise
