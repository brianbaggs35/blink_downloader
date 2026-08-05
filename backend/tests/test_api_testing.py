"""POST /api/testing/{reset,wipe,reset-baseline}: only reachable when
explicitly enabled, and each actually does what its name says when it is."""

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
from app.users.models import User
from tests.conftest import TEST_TABLES, PlainSettings, login


@pytest.mark.parametrize(
    "path", ["/api/testing/reset", "/api/testing/wipe", "/api/testing/reset-baseline"]
)
async def test_endpoint_is_a_404_when_not_enabled(client: AsyncClient, path: str) -> None:
    response = await client.post(path)
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


async def test_wipe_endpoint_invalidates_the_caller_s_own_session(
    reset_enabled_app: FastAPI, reset_enabled_client: AsyncClient, tmp_path: Path
) -> None:
    async with reset_enabled_app.state.sessionmaker() as session:
        await set_storage_dir(session, str(tmp_path))
        await seed_identity(session)

    await login(reset_enabled_client, E2E_ADMIN_EMAIL, E2E_ADMIN_PASSWORD)
    before = await reset_enabled_client.get("/api/users/me")
    assert before.status_code == 200

    wipe_response = await reset_enabled_client.post("/api/testing/wipe")
    assert wipe_response.status_code == 204

    # Unlike /reset, /wipe truncates users/access_tokens too - the caller's
    # own cookie no longer resolves to a real session.
    after = await reset_enabled_client.get("/api/users/me")
    assert after.status_code == 401

    async with reset_enabled_app.state.sessionmaker() as session:
        assert (await session.execute(select(User))).scalars().all() == []


async def test_wipe_endpoint_does_not_reseed_anything(
    reset_enabled_app: FastAPI, reset_enabled_client: AsyncClient, tmp_path: Path
) -> None:
    async with reset_enabled_app.state.sessionmaker() as session:
        await set_storage_dir(session, str(tmp_path))
        await seed_identity(session)

    response = await reset_enabled_client.post("/api/testing/wipe")
    assert response.status_code == 204

    async with reset_enabled_app.state.sessionmaker() as session:
        # onboarding.setup.ts's whole point: a genuinely empty database, not
        # just an empty users table - the wizard itself creates everything.
        assert (await session.execute(select(User))).scalars().all() == []
        assert (await session.execute(select(BlinkAccount))).scalars().all() == []


async def test_reset_baseline_endpoint_re_establishes_a_working_seeded_session(
    reset_enabled_app: FastAPI, reset_enabled_client: AsyncClient, tmp_path: Path
) -> None:
    async with reset_enabled_app.state.sessionmaker() as session:
        await set_storage_dir(session, str(tmp_path))
        await seed_identity(session)

    await login(reset_enabled_client, E2E_ADMIN_EMAIL, E2E_ADMIN_PASSWORD)
    before = await reset_enabled_client.get("/api/users/me")
    assert before.status_code == 200

    response = await reset_enabled_client.post("/api/testing/reset-baseline")
    assert response.status_code == 204

    # The old cookie's access_token row is gone along with the rest of
    # identity - this is exactly why auth.setup.ts must log in again
    # afterward rather than reusing a session captured before this ran.
    stale = await reset_enabled_client.get("/api/users/me")
    assert stale.status_code == 401

    # But the seeded admin account itself is back, under the same email/
    # password - a fresh login (overwriting the stale cookie) works.
    await login(reset_enabled_client, E2E_ADMIN_EMAIL, E2E_ADMIN_PASSWORD)
    me = await reset_enabled_client.get("/api/users/me")
    assert me.status_code == 200
    assert me.json()["email"] == E2E_ADMIN_EMAIL


async def test_reset_baseline_endpoint_reseeds_domain_data_too(
    reset_enabled_app: FastAPI, reset_enabled_client: AsyncClient, tmp_path: Path
) -> None:
    async with reset_enabled_app.state.sessionmaker() as session:
        await set_storage_dir(session, str(tmp_path))
        await seed_identity(session)

    response = await reset_enabled_client.post("/api/testing/reset-baseline")
    assert response.status_code == 204

    async with reset_enabled_app.state.sessionmaker() as session:
        accounts = (await session.execute(select(BlinkAccount))).scalars().all()
        assert len(accounts) == 1
