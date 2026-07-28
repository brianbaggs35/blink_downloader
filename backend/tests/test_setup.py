"""First-run setup: bootstraps exactly one admin, never an open registration."""

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select

from app.users.models import User
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD


async def test_status_uninitialized(client: AsyncClient) -> None:
    response = await client.get("/api/setup/status")
    assert response.status_code == 200
    assert response.json() == {"initialized": False}


async def test_setup_creates_admin(client: AsyncClient, app: FastAPI) -> None:
    response = await client.post(
        "/api/setup",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "display_name": "Brian"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == ADMIN_EMAIL
    assert body["is_superuser"] is True
    assert body["is_verified"] is True
    assert body["display_name"] == "Brian"
    assert body["timezone"] == "UTC"
    assert "password" not in body
    assert "hashed_password" not in body

    status = await client.get("/api/setup/status")
    assert status.json() == {"initialized": True}

    async with app.state.sessionmaker() as session:
        user = (await session.execute(select(User))).scalar_one()
    assert user.hashed_password.startswith("$argon2id$")
    assert ADMIN_PASSWORD not in user.hashed_password


async def test_setup_saves_the_chosen_timezone(client: AsyncClient) -> None:
    response = await client.post(
        "/api/setup",
        json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD,
            "timezone": "America/New_York",
        },
    )
    assert response.status_code == 201
    assert response.json()["timezone"] == "America/New_York"


async def test_setup_runs_only_once(admin_client: AsyncClient) -> None:
    response = await admin_client.post(
        "/api/setup",
        json={"email": "second@example.com", "password": "another-long-password"},
    )
    assert response.status_code == 409


async def test_short_password_rejected_by_schema(client: AsyncClient) -> None:
    response = await client.post("/api/setup", json={"email": ADMIN_EMAIL, "password": "short"})
    assert response.status_code == 422


async def test_password_containing_email_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/api/setup",
        json={"email": "a@b.com", "password": "xxA@B.comxxxx"},
    )
    assert response.status_code == 400
    assert "email" in response.json()["detail"].lower()


async def test_invalid_email_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/api/setup", json={"email": "not-an-email", "password": ADMIN_PASSWORD}
    )
    assert response.status_code == 422
