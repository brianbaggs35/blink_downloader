"""Cookie login/logout backed by revocable database session tokens."""

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select

from app.users.models import AccessToken
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD


async def _token_count(app: FastAPI) -> int:
    async with app.state.sessionmaker() as session:
        result = await session.execute(select(func.count()).select_from(AccessToken))
        return result.scalar_one()


async def test_login_sets_secure_cookie(client: AsyncClient, admin: dict[str, str]) -> None:
    response = await client.post(
        "/api/auth/login", data={"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    assert response.status_code == 204
    set_cookie = response.headers["set-cookie"]
    assert "blink_session=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Secure" in set_cookie
    assert "SameSite=lax" in set_cookie


async def test_login_creates_revocable_token(
    client: AsyncClient, admin: dict[str, str], app: FastAPI
) -> None:
    assert await _token_count(app) == 0
    await client.post("/api/auth/login", data={"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert await _token_count(app) == 1


async def test_me_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/users/me")
    assert response.status_code == 401


async def test_me_returns_profile(admin_client: AsyncClient) -> None:
    response = await admin_client.get("/api/users/me")
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == ADMIN_EMAIL
    assert body["display_name"] == "Admin"
    assert body["timezone"] == "UTC"


async def test_wrong_password_rejected(client: AsyncClient, admin: dict[str, str]) -> None:
    response = await client.post(
        "/api/auth/login", data={"username": ADMIN_EMAIL, "password": "wrong-password-123"}
    )
    assert response.status_code == 400


async def test_unknown_user_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/api/auth/login", data={"username": "ghost@example.com", "password": "irrelevant-123"}
    )
    assert response.status_code == 400


async def test_logout_revokes_session(admin_client: AsyncClient, app: FastAPI) -> None:
    assert await _token_count(app) == 1
    response = await admin_client.post("/api/auth/logout")
    assert response.status_code == 204
    assert await _token_count(app) == 0
    me = await admin_client.get("/api/users/me")
    assert me.status_code == 401
