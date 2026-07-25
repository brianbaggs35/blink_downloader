"""Profile updates, password change, and admin-only access to other users."""

import uuid

from fastapi import FastAPI
from fastapi_users.password import PasswordHelper
from httpx import AsyncClient

from app.users.models import User
from tests.conftest import ADMIN_PASSWORD, login

MEMBER_EMAIL = "member@example.com"
MEMBER_PASSWORD = "member-password-123"


async def _create_member(app: FastAPI) -> str:
    """Insert a non-admin user directly (no open registration to go through)."""
    user_id = uuid.uuid4()
    async with app.state.sessionmaker() as session:
        session.add(
            User(
                id=user_id,
                email=MEMBER_EMAIL,
                hashed_password=PasswordHelper().hash(MEMBER_PASSWORD),
                is_active=True,
                is_superuser=False,
                is_verified=True,
                display_name="Member",
            )
        )
        await session.commit()
    return str(user_id)


async def test_update_profile(admin_client: AsyncClient) -> None:
    response = await admin_client.patch(
        "/api/users/me",
        json={"display_name": "Brian", "timezone": "America/New_York"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["display_name"] == "Brian"
    assert body["timezone"] == "America/New_York"


async def test_change_password_and_relogin(admin_client: AsyncClient) -> None:
    new_password = "an-even-longer-password-42"
    response = await admin_client.patch("/api/users/me", json={"password": new_password})
    assert response.status_code == 200
    await admin_client.post("/api/auth/logout")
    response = await admin_client.post(
        "/api/auth/login", data={"username": "admin@example.com", "password": ADMIN_PASSWORD}
    )
    assert response.status_code == 400  # old password no longer valid
    await login(admin_client, "admin@example.com", new_password)


async def test_weak_new_password_rejected(admin_client: AsyncClient) -> None:
    response = await admin_client.patch("/api/users/me", json={"password": "short"})
    assert response.status_code == 400


async def test_admin_can_read_other_users(admin_client: AsyncClient, app: FastAPI) -> None:
    member_id = await _create_member(app)
    response = await admin_client.get(f"/api/users/{member_id}")
    assert response.status_code == 200
    assert response.json()["email"] == MEMBER_EMAIL


async def test_member_cannot_read_other_users(
    client: AsyncClient, admin: dict[str, str], app: FastAPI
) -> None:
    await _create_member(app)
    await login(client, MEMBER_EMAIL, MEMBER_PASSWORD)
    response = await client.get(f"/api/users/{admin['id']}")
    assert response.status_code == 403
