"""e2e fixture seeding is idempotent and produces a usable admin."""

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import text

from app.testing.seed import E2E_ADMIN_EMAIL, E2E_ADMIN_PASSWORD, seed
from tests.conftest import login


async def test_seed_creates_admin_once(client: AsyncClient, app: FastAPI) -> None:
    assert await seed() is True
    assert await seed() is False  # idempotent

    await login(client, E2E_ADMIN_EMAIL, E2E_ADMIN_PASSWORD)
    me = await client.get("/api/users/me")
    assert me.status_code == 200
    assert me.json()["is_superuser"] is True

    # Leave a clean slate for other tests (client fixture truncates pre-test too).
    async with app.state.sessionmaker() as session:
        await session.execute(text("TRUNCATE TABLE access_tokens, users CASCADE"))
        await session.commit()
