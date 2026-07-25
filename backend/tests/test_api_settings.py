"""GET/PATCH /api/settings/storage."""

from httpx import AsyncClient


async def test_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/settings/storage")
    assert response.status_code == 401


async def test_default_reflects_env_var(admin_client: AsyncClient) -> None:
    response = await admin_client.get("/api/settings/storage")
    assert response.status_code == 200
    body = response.json()
    assert body["is_default"] is True
    assert body["storage_dir"]


async def test_update_to_a_writable_directory(admin_client: AsyncClient, tmp_path: object) -> None:
    new_dir = str(tmp_path) + "/clips"
    response = await admin_client.patch("/api/settings/storage", json={"storage_dir": new_dir})
    assert response.status_code == 200
    body = response.json()
    assert body["storage_dir"] == new_dir
    assert body["is_default"] is False

    followup = await admin_client.get("/api/settings/storage")
    assert followup.json()["storage_dir"] == new_dir


async def test_clearing_the_override_restores_default(
    admin_client: AsyncClient, tmp_path: object
) -> None:
    await admin_client.patch("/api/settings/storage", json={"storage_dir": str(tmp_path)})
    response = await admin_client.patch("/api/settings/storage", json={"storage_dir": None})
    assert response.status_code == 200
    assert response.json()["is_default"] is True


async def test_relative_path_rejected_by_schema(admin_client: AsyncClient) -> None:
    response = await admin_client.patch(
        "/api/settings/storage", json={"storage_dir": "relative/path"}
    )
    assert response.status_code == 422


async def test_unwritable_path_rejected(admin_client: AsyncClient) -> None:
    response = await admin_client.patch(
        "/api/settings/storage", json={"storage_dir": "/proc/blink-cannot-write-here"}
    )
    assert response.status_code == 400
    assert "not exist or is not writable" in response.json()["detail"]
