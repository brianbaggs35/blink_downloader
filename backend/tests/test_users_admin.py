"""/api/users (admin list+invite) on top of fastapi-users' own /me and /{id}."""

from httpx import AsyncClient


async def test_list_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/users")
    assert response.status_code == 401


async def test_list_returns_created_accounts(admin_client: AsyncClient) -> None:
    await admin_client.post(
        "/api/users",
        json={
            "email": "second@example.com",
            "password": "a-fine-long-password",
            "is_superuser": False,
        },
    )
    response = await admin_client.get("/api/users")
    assert response.status_code == 200
    emails = {u["email"] for u in response.json()}
    assert emails == {"admin@example.com", "second@example.com"}


async def test_create_a_viewer_account(admin_client: AsyncClient) -> None:
    response = await admin_client.post(
        "/api/users",
        json={
            "email": "viewer2@example.com",
            "password": "a-fine-long-password",
            "display_name": "Viewer Two",
            "is_superuser": False,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["is_superuser"] is False
    assert body["is_verified"] is True
    assert body["display_name"] == "Viewer Two"


async def test_create_rejects_a_weak_password(admin_client: AsyncClient) -> None:
    response = await admin_client.post(
        "/api/users", json={"email": "weak@example.com", "password": "short"}
    )
    assert response.status_code == 400


async def test_create_rejects_a_duplicate_email(admin_client: AsyncClient) -> None:
    response = await admin_client.post(
        "/api/users",
        json={"email": "admin@example.com", "password": "a-fine-long-password"},
    )
    assert response.status_code == 400
    assert "already exists" in response.json()["detail"]


async def test_create_requires_admin(viewer_client: AsyncClient) -> None:
    response = await viewer_client.post(
        "/api/users", json={"email": "nope@example.com", "password": "a-fine-long-password"}
    )
    assert response.status_code == 403


async def test_list_requires_admin(viewer_client: AsyncClient) -> None:
    response = await viewer_client.get("/api/users")
    assert response.status_code == 403


async def test_viewer_can_still_read_their_own_profile(viewer_client: AsyncClient) -> None:
    response = await viewer_client.get("/api/users/me")
    assert response.status_code == 200
    assert response.json()["is_superuser"] is False
