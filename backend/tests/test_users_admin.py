"""/api/users (admin list+invite+edit+remove) on top of fastapi-users' own
/me and GET /{id}."""

import uuid

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from tests.conftest import login


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


async def _second_client(app: FastAPI) -> AsyncClient:
    """A second, independent session on the same app - needed whenever a
    test wants two authenticated identities alive at once (admin_client and
    viewer_client share a single session, per its own docstring)."""
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="https://testserver")


async def test_update_edits_display_name(admin_client: AsyncClient) -> None:
    created = await admin_client.post(
        "/api/users",
        json={
            "email": "target@example.com",
            "password": "a-fine-long-password",
            "display_name": "Original Name",
            "is_superuser": False,
        },
    )
    user_id = created.json()["id"]

    response = await admin_client.patch(
        f"/api/users/{user_id}",
        json={"display_name": "New Name", "is_superuser": False},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["display_name"] == "New Name"
    assert body["is_superuser"] is False


async def test_update_can_promote_a_viewer_to_admin(admin_client: AsyncClient) -> None:
    created = await admin_client.post(
        "/api/users",
        json={
            "email": "target@example.com",
            "password": "a-fine-long-password",
            "display_name": "Target",
            "is_superuser": False,
        },
    )
    user_id = created.json()["id"]

    response = await admin_client.patch(
        f"/api/users/{user_id}",
        json={"display_name": "Target", "is_superuser": True},
    )

    assert response.status_code == 200, response.text
    assert response.json()["is_superuser"] is True


async def test_update_can_reset_password(app: FastAPI, admin_client: AsyncClient) -> None:
    created = await admin_client.post(
        "/api/users",
        json={
            "email": "target@example.com",
            "password": "the-original-password",
            "display_name": "Target",
            "is_superuser": False,
        },
    )
    user_id = created.json()["id"]

    response = await admin_client.patch(
        f"/api/users/{user_id}",
        json={"display_name": "Target", "is_superuser": False, "password": "a-brand-new-password"},
    )
    assert response.status_code == 200, response.text

    async with await _second_client(app) as target_client:
        await login(target_client, "target@example.com", "a-brand-new-password")


async def test_update_without_a_password_leaves_the_existing_one_usable(
    app: FastAPI, admin_client: AsyncClient
) -> None:
    created = await admin_client.post(
        "/api/users",
        json={
            "email": "target@example.com",
            "password": "the-original-password",
            "display_name": "Target",
            "is_superuser": False,
        },
    )
    user_id = created.json()["id"]

    response = await admin_client.patch(
        f"/api/users/{user_id}",
        json={"display_name": "Renamed", "is_superuser": False},
    )
    assert response.status_code == 200, response.text

    async with await _second_client(app) as target_client:
        await login(target_client, "target@example.com", "the-original-password")


async def test_update_rejects_a_weak_password(admin_client: AsyncClient) -> None:
    created = await admin_client.post(
        "/api/users",
        json={
            "email": "target@example.com",
            "password": "a-fine-long-password",
            "is_superuser": False,
        },
    )
    user_id = created.json()["id"]

    response = await admin_client.patch(
        f"/api/users/{user_id}",
        json={"display_name": "Target", "is_superuser": False, "password": "short"},
    )

    assert response.status_code == 400


async def test_update_requires_admin(viewer_client: AsyncClient) -> None:
    response = await viewer_client.patch(
        f"/api/users/{uuid.uuid4()}",
        json={"display_name": "Nope", "is_superuser": False},
    )
    assert response.status_code == 403


async def test_update_404s_for_an_unknown_user(admin_client: AsyncClient) -> None:
    response = await admin_client.patch(
        f"/api/users/{uuid.uuid4()}",
        json={"display_name": "Nope", "is_superuser": False},
    )
    assert response.status_code == 404


async def test_update_blocks_self_demotion_as_the_sole_admin(
    admin_client: AsyncClient, admin: dict[str, str]
) -> None:
    response = await admin_client.patch(
        f"/api/users/{admin['id']}",
        json={"display_name": "Admin", "is_superuser": False},
    )

    assert response.status_code == 400
    assert "last administrator" in response.json()["detail"]


async def test_update_allows_self_demotion_when_another_admin_exists(
    admin_client: AsyncClient, admin: dict[str, str]
) -> None:
    await admin_client.post(
        "/api/users",
        json={
            "email": "second-admin@example.com",
            "password": "a-fine-long-password",
            "is_superuser": True,
        },
    )

    response = await admin_client.patch(
        f"/api/users/{admin['id']}",
        json={"display_name": "Admin", "is_superuser": False},
    )

    assert response.status_code == 200, response.text
    assert response.json()["is_superuser"] is False


async def test_delete_removes_the_target_user(admin_client: AsyncClient) -> None:
    created = await admin_client.post(
        "/api/users",
        json={
            "email": "target@example.com",
            "password": "a-fine-long-password",
            "is_superuser": False,
        },
    )
    user_id = created.json()["id"]

    response = await admin_client.delete(f"/api/users/{user_id}")
    assert response.status_code == 204

    remaining = await admin_client.get("/api/users")
    assert "target@example.com" not in {u["email"] for u in remaining.json()}


async def test_delete_blocks_deleting_yourself(
    admin_client: AsyncClient, admin: dict[str, str]
) -> None:
    response = await admin_client.delete(f"/api/users/{admin['id']}")

    assert response.status_code == 400
    assert "own account" in response.json()["detail"]


async def test_delete_requires_admin(viewer_client: AsyncClient) -> None:
    response = await viewer_client.delete(f"/api/users/{uuid.uuid4()}")
    assert response.status_code == 403


async def test_delete_404s_for_an_unknown_user(admin_client: AsyncClient) -> None:
    response = await admin_client.delete(f"/api/users/{uuid.uuid4()}")
    assert response.status_code == 404
