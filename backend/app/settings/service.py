"""Read/write access to the singleton settings row, with sensible fallbacks."""

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.settings.models import SINGLETON_ID, AppSettings
from app.settings.schemas import BlinkSyncSettingsUpdate


async def get_app_settings(session: AsyncSession) -> AppSettings:
    row = await session.get(AppSettings, SINGLETON_ID)
    if row is None:
        row = AppSettings(id=SINGLETON_ID)
        session.add(row)
        await session.flush()
    return row


async def set_storage_dir(session: AsyncSession, storage_dir: str | None) -> AppSettings:
    row = await get_app_settings(session)
    row.storage_dir = storage_dir
    await session.commit()
    await session.refresh(row)
    return row


async def set_local_storage_quota_bytes(
    session: AsyncSession, quota_bytes: int | None
) -> AppSettings:
    row = await get_app_settings(session)
    row.local_storage_quota_bytes = quota_bytes
    await session.commit()
    await session.refresh(row)
    return row


async def resolve_storage_dir(session: AsyncSession, settings: Settings) -> Path:
    """The effective clip storage root: DB override, else the env default."""
    row = await get_app_settings(session)
    return Path(row.storage_dir) if row.storage_dir else settings.storage_dir


async def resolve_blink_sync_interval_seconds(session: AsyncSession, settings: Settings) -> int:
    row = await get_app_settings(session)
    return row.blink_sync_interval_seconds or settings.blink_sync_interval_seconds


async def resolve_blink_initial_sync_days(session: AsyncSession, settings: Settings) -> int:
    row = await get_app_settings(session)
    return row.blink_initial_sync_days or settings.blink_initial_sync_days


async def resolve_blink_auto_analyze_limit(session: AsyncSession, settings: Settings) -> int:
    row = await get_app_settings(session)
    return row.blink_auto_analyze_limit or settings.blink_auto_analyze_limit


async def set_blink_sync_settings(
    session: AsyncSession, payload: BlinkSyncSettingsUpdate
) -> AppSettings:
    row = await get_app_settings(session)
    row.blink_sync_interval_seconds = payload.sync_interval_seconds
    row.blink_initial_sync_days = payload.initial_sync_days
    row.blink_auto_analyze_limit = payload.auto_analyze_limit
    await session.commit()
    await session.refresh(row)
    return row
