"""Read/write access to the singleton settings row, with sensible fallbacks."""

from pathlib import Path

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.settings.models import SINGLETON_ID, AppSettings


async def get_app_settings(session: AsyncSession) -> AppSettings:
    row = await session.get(AppSettings, SINGLETON_ID)
    if row is None:
        row = AppSettings(id=SINGLETON_ID)
        session.add(row)
        await session.flush()
    return row


async def set_storage_dir(session: AsyncSession, storage_dir: str | None) -> AppSettings:
    stmt = (
        insert(AppSettings)
        .values(id=SINGLETON_ID, storage_dir=storage_dir)
        .on_conflict_do_update(index_elements=[AppSettings.id], set_={"storage_dir": storage_dir})
        .returning(AppSettings)
    )
    result = await session.execute(stmt)
    await session.commit()
    return result.scalar_one()


async def resolve_storage_dir(session: AsyncSession, settings: Settings) -> Path:
    """The effective clip storage root: DB override, else the env default."""
    row = await get_app_settings(session)
    return Path(row.storage_dir) if row.storage_dir else settings.storage_dir
