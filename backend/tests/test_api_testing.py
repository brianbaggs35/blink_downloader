"""POST /api/testing/reset: only reachable when explicitly enabled, and
actually resets to the seeded baseline when it is."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from app.blink.models import BlinkAccount
from app.main import create_app
from app.settings.service import set_storage_dir
from app.testing.seed import E2E_ADMIN_EMAIL, E2E_ADMIN_PASSWORD, seed_identity
from tests.conftest import TEST_TABLES, PlainSettings, login


async def test_reset_endpoint_is_a_404_when_not_enabled(client: AsyncClient) -> None:
    response = await client.post("/api/testing/reset")
    assert response.status_code == 404


@pytest.fixture
def reset_enabled_app() -> FastAPI:
    return create_app(PlainSettings(enable_test_reset_endpoint=True))


@pytest.fixture
async def reset_enabled_client(reset_enabled_app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with LifespanManager(reset_enabled_app):
        async with reset_enabled_app.state.sessionmaker() as session:
            await session.execute(text(f"TRUNCATE TABLE {TEST_TABLES} CASCADE"))
            await session.commit()
        transport = ASGITransport(app=reset_enabled_app)
        async with AsyncClient(transport=transport, base_url="https://testserver") as c:
            yield c


async def test_reset_endpoint_wipes_domain_data_and_reseeds(
    reset_enabled_app: FastAPI, reset_enabled_client: AsyncClient, tmp_path: Path
) -> None:
    async with reset_enabled_app.state.sessionmaker() as session:
        await set_storage_dir(session, str(tmp_path))
        await seed_identity(session)
        # A marker row seed_data() itself never creates with this identity -
        # proves the endpoint actually truncates rather than being a no-op.
        session.add(
            BlinkAccount(
                encrypted_username="not-real",
                encrypted_password="not-real",
                encrypted_token_data="{}",
            )
        )
        await session.commit()
        marker_accounts = (await session.execute(select(BlinkAccount))).scalars().all()
        assert len(marker_accounts) == 1

    response = await reset_enabled_client.post("/api/testing/reset")
    assert response.status_code == 204

    async with reset_enabled_app.state.sessionmaker() as session:
        accounts = (await session.execute(select(BlinkAccount))).scalars().all()
        # The marker account is gone; the one real seed_data() creates (with
        # its own deterministic id) is back.
        assert len(accounts) == 1
        assert accounts[0].encrypted_username != "not-real"


async def test_reset_endpoint_preserves_the_caller_s_own_session(
    reset_enabled_app: FastAPI, reset_enabled_client: AsyncClient, tmp_path: Path
) -> None:
    async with reset_enabled_app.state.sessionmaker() as session:
        await set_storage_dir(session, str(tmp_path))
        await seed_identity(session)

    await login(reset_enabled_client, E2E_ADMIN_EMAIL, E2E_ADMIN_PASSWORD)
    before = await reset_enabled_client.get("/api/users/me")
    assert before.status_code == 200

    reset_response = await reset_enabled_client.post("/api/testing/reset")
    assert reset_response.status_code == 204

    # Still logged in with the same cookie - the reset never touched
    # users/access_tokens.
    after = await reset_enabled_client.get("/api/users/me")
    assert after.status_code == 200
    assert after.json()["email"] == E2E_ADMIN_EMAIL
