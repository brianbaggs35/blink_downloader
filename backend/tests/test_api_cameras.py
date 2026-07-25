"""GET /api/cameras, PATCH /api/cameras/{id}."""

import uuid

from fastapi import FastAPI
from httpx import AsyncClient

from app.blink.models import BlinkAccount, Camera
from app.config import get_settings
from app.security.crypto import SecretBox


async def _make_camera(app: FastAPI, name: str = "Front Door") -> Camera:
    # admin_client/client have already entered the app's lifespan by the time
    # a test body runs, so app.state.sessionmaker is live — reuse it instead
    # of a second fixture that would re-enter (and double-init) the lifespan.
    async with app.state.sessionmaker() as session:
        box = SecretBox(get_settings().encryption_key)
        account = BlinkAccount(
            encrypted_username=box.encrypt("u"),
            encrypted_password=box.encrypt("p"),
            encrypted_token_data=box.encrypt("{}"),
        )
        session.add(account)
        await session.flush()
        camera = Camera(
            blink_account_id=account.id,
            blink_camera_id="cam-1",
            blink_network_id="net-1",
            name=name,
            camera_type="catalina",
        )
        session.add(camera)
        await session.commit()
        await session.refresh(camera)
        return camera


async def test_list_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/cameras")
    assert response.status_code == 401


async def test_list_is_empty_with_no_cameras(admin_client: AsyncClient) -> None:
    response = await admin_client.get("/api/cameras")
    assert response.status_code == 200
    assert response.json() == []


async def test_list_returns_cameras_ordered_by_name(
    admin_client: AsyncClient, app: FastAPI
) -> None:
    await _make_camera(app, name="Zebra Cam")
    await _make_camera(app, name="Alpha Cam")

    response = await admin_client.get("/api/cameras")
    assert response.status_code == 200
    names = [c["name"] for c in response.json()]
    assert names == ["Alpha Cam", "Zebra Cam"]


async def test_update_unknown_camera_is_404(admin_client: AsyncClient) -> None:
    response = await admin_client.patch(f"/api/cameras/{uuid.uuid4()}", json={"enabled": False})
    assert response.status_code == 404


async def test_update_toggles_enabled(admin_client: AsyncClient, app: FastAPI) -> None:
    camera = await _make_camera(app)
    response = await admin_client.patch(f"/api/cameras/{camera.id}", json={"enabled": False})
    assert response.status_code == 200
    assert response.json()["enabled"] is False


async def test_update_requires_superuser(client: AsyncClient, app: FastAPI) -> None:
    camera = await _make_camera(app)
    response = await client.patch(f"/api/cameras/{camera.id}", json={"enabled": False})
    assert response.status_code == 401


async def test_update_sets_security_context(admin_client: AsyncClient, app: FastAPI) -> None:
    camera = await _make_camera(app)
    response = await admin_client.patch(
        f"/api/cameras/{camera.id}",
        json={"enabled": True, "security_context": "Watches the driveway and front walkway."},
    )
    assert response.status_code == 200
    assert response.json()["security_context"] == "Watches the driveway and front walkway."


async def test_update_without_security_context_clears_it(
    admin_client: AsyncClient, app: FastAPI
) -> None:
    camera = await _make_camera(app)
    await admin_client.patch(
        f"/api/cameras/{camera.id}", json={"enabled": True, "security_context": "Front door"}
    )
    response = await admin_client.patch(f"/api/cameras/{camera.id}", json={"enabled": True})
    assert response.status_code == 200
    assert response.json()["security_context"] is None
