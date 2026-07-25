"""Shared fixtures: real Postgres + Redis (docker-compose.test.yml / CI services)."""

# redis-py 5.x (capped by arq) ships partial type annotations.
# pyright: reportUnknownMemberType=false

import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

os.environ["BLINK_ENVIRONMENT"] = "test"
os.environ.setdefault(
    "BLINK_DATABASE_URL", "postgresql+asyncpg://blink:blink@localhost:55432/blink_test"
)
os.environ.setdefault("BLINK_REDIS_URL", "redis://localhost:63790/0")
os.environ.setdefault("BLINK_SECRET_KEY", "test-secret-key-not-for-production-use")
os.environ.setdefault("BLINK_ENCRYPTION_KEY", "iRZbYNDbXbGGoHy4JV2XChcPYDbdCTC9YXf29CQzB1I=")

import pytest
from alembic.config import Config as AlembicConfig
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic_settings import SettingsConfigDict
from redis.asyncio import Redis
from sqlalchemy import text

from alembic import command
from app.config import Settings
from app.main import create_app

BACKEND_DIR = Path(__file__).resolve().parent.parent

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "correct-horse-battery-staple"


class PlainSettings(Settings):
    """Settings that ignore any .env file, for deterministic construction in tests."""

    model_config = SettingsConfigDict(env_prefix="BLINK_", env_file=None, extra="ignore")


def _alembic_config() -> AlembicConfig:
    cfg = AlembicConfig(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return cfg


@pytest.fixture(scope="session", autouse=True)
def apply_migrations() -> Any:
    cfg = _alembic_config()
    command.upgrade(cfg, "head")
    yield
    command.downgrade(cfg, "base")


@pytest.fixture
def app() -> FastAPI:
    return create_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with LifespanManager(app):
        async with app.state.sessionmaker() as session:
            await session.execute(text("TRUNCATE TABLE access_tokens, users CASCADE"))
            await session.commit()
        await app.state.redis.flushdb()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="https://testserver") as c:
            yield c


@pytest.fixture
async def redis() -> AsyncIterator[Redis]:
    r = Redis.from_url(os.environ["BLINK_REDIS_URL"], decode_responses=True)
    await r.flushdb()
    yield r
    await r.aclose()


@pytest.fixture
async def admin(client: AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/setup",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "display_name": "Admin"},
    )
    assert response.status_code == 201, response.text
    return {"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "id": response.json()["id"]}


async def login(client: AsyncClient, email: str, password: str) -> None:
    response = await client.post("/api/auth/login", data={"username": email, "password": password})
    assert response.status_code == 204, response.text


@pytest.fixture
async def admin_client(client: AsyncClient, admin: dict[str, str]) -> AsyncClient:
    await login(client, admin["email"], admin["password"])
    return client
