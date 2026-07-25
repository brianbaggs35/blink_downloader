"""Singleton app_settings row: get-or-create, update, and effective-path resolution."""

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.settings.models import SINGLETON_ID
from app.settings.service import get_app_settings, resolve_storage_dir, set_storage_dir
from tests.conftest import PlainSettings


async def test_get_app_settings_creates_the_row_on_first_read(app_session: AsyncSession) -> None:
    row = await get_app_settings(app_session)
    assert row.id == SINGLETON_ID
    assert row.storage_dir is None


async def test_get_app_settings_is_idempotent(app_session: AsyncSession) -> None:
    first = await get_app_settings(app_session)
    await app_session.commit()
    second = await get_app_settings(app_session)
    assert first.id == second.id


async def test_set_storage_dir_creates_then_updates(app_session: AsyncSession) -> None:
    await set_storage_dir(app_session, "/mnt/clips")
    row = await get_app_settings(app_session)
    assert row.storage_dir == "/mnt/clips"

    await set_storage_dir(app_session, "/mnt/other")
    row = await get_app_settings(app_session)
    assert row.storage_dir == "/mnt/other"


async def test_set_storage_dir_can_clear_the_override(app_session: AsyncSession) -> None:
    await set_storage_dir(app_session, "/mnt/clips")
    await set_storage_dir(app_session, None)
    row = await get_app_settings(app_session)
    assert row.storage_dir is None


async def test_resolve_storage_dir_falls_back_to_env_default(app_session: AsyncSession) -> None:
    settings = PlainSettings(storage_dir=Path("/data/clips"))
    resolved = await resolve_storage_dir(app_session, settings)
    assert resolved == Path("/data/clips")


async def test_resolve_storage_dir_prefers_db_override(app_session: AsyncSession) -> None:
    await set_storage_dir(app_session, "/mnt/clips")
    settings = PlainSettings(storage_dir=Path("/data/clips"))
    resolved = await resolve_storage_dir(app_session, settings)
    assert resolved == Path("/mnt/clips")
