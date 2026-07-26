"""GET /api/cameras, PATCH /api/cameras/{id}, preview, record.

BlinkPyService is faked (patched at the name imported into
app.livefeed.service) for the preview/record endpoints, matching
test_worker_download.py's convention.
"""

# pytest calls autouse fixtures implicitly; pyright can't see that usage.
# pyright: reportUnusedFunction=false

import uuid
from pathlib import Path
from typing import Any, ClassVar

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.blink.models import BlinkAccount, Camera
from app.blink.service import BlinkAuthError, BlinkError
from app.config import get_settings
from app.security.crypto import SecretBox
from app.settings.service import set_storage_dir


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


# ------------------------------------------------------------------ preview


class FakeBlinkService:
    next_error: ClassVar[Exception | None] = None

    def __init__(self, token_data: dict[str, Any]) -> None:
        del token_data

    async def get_camera_preview(self, camera_id: str) -> bytes:
        del camera_id
        if FakeBlinkService.next_error:
            raise FakeBlinkService.next_error
        return b"preview-bytes"

    async def snap_camera_picture(self, camera_id: str) -> bytes:
        del camera_id
        if FakeBlinkService.next_error:
            raise FakeBlinkService.next_error
        return b"snapshot-bytes"

    async def record_clip(self, camera_id: str) -> None:
        del camera_id
        if FakeBlinkService.next_error:
            raise FakeBlinkService.next_error

    async def close(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _reset_fake_blink_service(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeBlinkService.next_error = None
    monkeypatch.setattr("app.livefeed.service.BlinkPyService", FakeBlinkService)


async def _use_storage(app: FastAPI, tmp_path: Path) -> None:
    async with app.state.sessionmaker() as session:
        await set_storage_dir(session, str(tmp_path))


async def test_preview_requires_authentication(client: AsyncClient, app: FastAPI) -> None:
    camera = await _make_camera(app)
    response = await client.get(f"/api/cameras/{camera.id}/preview")
    assert response.status_code == 401


async def test_preview_unknown_camera_is_404(admin_client: AsyncClient) -> None:
    response = await admin_client.get(f"/api/cameras/{uuid.uuid4()}/preview")
    assert response.status_code == 404


async def test_preview_passive_fetch_available_to_a_viewer(
    viewer_client: AsyncClient, app: FastAPI, tmp_path: Path
) -> None:
    await _use_storage(app, tmp_path)
    camera = await _make_camera(app)
    response = await viewer_client.get(f"/api/cameras/{camera.id}/preview")
    assert response.status_code == 200
    assert response.content == b"preview-bytes"
    assert response.headers["cache-control"] == "no-store"
    assert "x-preview-updated-at" in {k.lower() for k in response.headers}


async def test_preview_forced_snap_rejected_for_a_viewer(
    viewer_client: AsyncClient, app: FastAPI, tmp_path: Path
) -> None:
    await _use_storage(app, tmp_path)
    camera = await _make_camera(app)
    response = await viewer_client.get(f"/api/cameras/{camera.id}/preview", params={"force": True})
    assert response.status_code == 403


async def test_preview_forced_snap_allowed_for_an_admin(
    admin_client: AsyncClient, app: FastAPI, tmp_path: Path
) -> None:
    await _use_storage(app, tmp_path)
    camera = await _make_camera(app)
    response = await admin_client.get(f"/api/cameras/{camera.id}/preview", params={"force": True})
    assert response.status_code == 200
    assert response.content == b"snapshot-bytes"


async def test_preview_maps_auth_errors_to_401(
    admin_client: AsyncClient, app: FastAPI, tmp_path: Path
) -> None:
    await _use_storage(app, tmp_path)
    camera = await _make_camera(app)
    FakeBlinkService.next_error = BlinkAuthError("token expired")
    response = await admin_client.get(f"/api/cameras/{camera.id}/preview")
    assert response.status_code == 401


async def test_preview_maps_generic_blink_errors_to_502(
    admin_client: AsyncClient, app: FastAPI, tmp_path: Path
) -> None:
    await _use_storage(app, tmp_path)
    camera = await _make_camera(app)
    FakeBlinkService.next_error = BlinkError("camera offline")
    response = await admin_client.get(f"/api/cameras/{camera.id}/preview")
    assert response.status_code == 502


# ------------------------------------------------------------------- record


async def test_record_requires_authentication(client: AsyncClient, app: FastAPI) -> None:
    camera = await _make_camera(app)
    response = await client.post(f"/api/cameras/{camera.id}/record")
    assert response.status_code == 401


async def test_record_requires_superuser(viewer_client: AsyncClient, app: FastAPI) -> None:
    camera = await _make_camera(app)
    response = await viewer_client.post(f"/api/cameras/{camera.id}/record")
    assert response.status_code == 403


async def test_record_unknown_camera_is_404(admin_client: AsyncClient) -> None:
    response = await admin_client.post(f"/api/cameras/{uuid.uuid4()}/record")
    assert response.status_code == 404


async def test_record_succeeds(admin_client: AsyncClient, app: FastAPI) -> None:
    camera = await _make_camera(app)
    response = await admin_client.post(f"/api/cameras/{camera.id}/record")
    assert response.status_code == 202
    assert response.json() == {"status": "recording_started"}


async def test_record_maps_auth_errors_to_401(admin_client: AsyncClient, app: FastAPI) -> None:
    camera = await _make_camera(app)
    FakeBlinkService.next_error = BlinkAuthError("token expired")
    response = await admin_client.post(f"/api/cameras/{camera.id}/record")
    assert response.status_code == 401


async def test_record_maps_generic_blink_errors_to_502(
    admin_client: AsyncClient, app: FastAPI
) -> None:
    camera = await _make_camera(app)
    FakeBlinkService.next_error = BlinkError("camera offline")
    response = await admin_client.post(f"/api/cameras/{camera.id}/record")
    assert response.status_code == 502
