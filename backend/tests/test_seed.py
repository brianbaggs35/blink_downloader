"""e2e fixture seeding is idempotent and produces a usable admin + demo data."""

from pathlib import Path

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select, text

from app.biometrics.models import Person
from app.blink.models import Clip
from app.settings.service import set_storage_dir
from app.testing.seed import DEMO_PERSON_NAME, E2E_ADMIN_EMAIL, E2E_ADMIN_PASSWORD, seed
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
        assert len(clips) == 6
        downloaded = [c for c in clips if c.downloaded_at is not None]
        assert len(downloaded) == 5
        for clip in downloaded:
            assert clip.storage_path is not None
            assert Path(clip.storage_path).exists()

        person = (
            await session.execute(select(Person).where(Person.name == DEMO_PERSON_NAME))
        ).scalar_one()
        assert person.thumbnail_path is not None
        assert Path(person.thumbnail_path).exists()

    # Leave a clean slate for other tests (client fixture truncates pre-test too).
    async with app.state.sessionmaker() as session:
        await session.execute(
            text("TRUNCATE TABLE access_tokens, users, blink_accounts, people, analyses CASCADE")
        )
        await session.commit()
