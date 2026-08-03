"""GET /api/cameras, PATCH /api/cameras/{id}, preview, record.

BlinkPyService is faked (patched at the name imported into
app.livefeed.service) for the preview/record endpoints, matching
test_worker_download.py's convention.
"""

# pytest calls autouse fixtures implicitly; pyright can't see that usage.
# pyright: reportUnusedFunction=false

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.blink.models import BlinkAccount, Camera
from app.blink.service import BlinkAuthError, BlinkError, LiveViewUnsupportedError
from app.config import get_settings
from app.livefeed.live_stream import LiveViewStartError
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

    async def init_live_stream(self, camera_id: str) -> Any:
        del camera_id
        if FakeBlinkService.next_error:
            raise FakeBlinkService.next_error
        return object()

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


# --------------------------------------------------------------- live view


@dataclass
class _FakeSession:
    session_id: uuid.UUID
    camera_id: uuid.UUID


class FakeLiveViewManager:
    def __init__(self) -> None:
        self.start_calls: list[uuid.UUID] = []
        self.stop_calls: list[uuid.UUID] = []
        self.get_file_calls: list[tuple[uuid.UUID, str]] = []
        self.next_error: Exception | None = None
        self.file_to_serve: Path | None = None
        self.sessions: dict[uuid.UUID, _FakeSession] = {}

    async def start_session(self, camera_id: uuid.UUID, service: Any, handle: Any) -> _FakeSession:
        del service, handle
        self.start_calls.append(camera_id)
        if self.next_error:
            raise self.next_error
        session = _FakeSession(session_id=uuid.uuid4(), camera_id=camera_id)
        self.sessions[session.session_id] = session
        return session

    def get(self, session_id: uuid.UUID) -> _FakeSession | None:
        return self.sessions.get(session_id)

    async def stop_session(self, session_id: uuid.UUID) -> None:
        self.stop_calls.append(session_id)
        self.sessions.pop(session_id, None)

    def get_file(self, session_id: uuid.UUID, filename: str) -> Path | None:
        self.get_file_calls.append((session_id, filename))
        return self.file_to_serve

    async def aclose(self) -> None:
        """The app's real lifespan shutdown always calls this on whatever
        app.state.live_view_manager currently is - the real manager's
        aclose() is exercised in test_live_stream_manager.py; this only
        needs to exist so overwriting app.state with a fake doesn't break
        every test's teardown."""


def _install_fake_manager(app: FastAPI) -> FakeLiveViewManager:
    manager = FakeLiveViewManager()
    app.state.live_view_manager = manager
    return manager


async def test_start_live_view_requires_authentication(client: AsyncClient, app: FastAPI) -> None:
    camera = await _make_camera(app)
    response = await client.post(f"/api/cameras/{camera.id}/live-view/start")
    assert response.status_code == 401


async def test_start_live_view_requires_superuser(viewer_client: AsyncClient, app: FastAPI) -> None:
    _install_fake_manager(app)
    camera = await _make_camera(app)
    response = await viewer_client.post(f"/api/cameras/{camera.id}/live-view/start")
    assert response.status_code == 403


async def test_start_live_view_unknown_camera_is_404(
    admin_client: AsyncClient, app: FastAPI
) -> None:
    _install_fake_manager(app)
    response = await admin_client.post(f"/api/cameras/{uuid.uuid4()}/live-view/start")
    assert response.status_code == 404


async def test_start_live_view_succeeds(admin_client: AsyncClient, app: FastAPI) -> None:
    manager = _install_fake_manager(app)
    camera = await _make_camera(app)

    response = await admin_client.post(f"/api/cameras/{camera.id}/live-view/start")

    assert response.status_code == 201
    body = response.json()
    assert body["camera_id"] == str(camera.id)
    assert body["playlist_url"] == (
        f"/api/cameras/{camera.id}/live-view/{body['session_id']}/stream.m3u8"
    )
    assert manager.start_calls == [camera.id]


async def test_start_live_view_maps_auth_errors_to_401(
    admin_client: AsyncClient, app: FastAPI
) -> None:
    _install_fake_manager(app)
    camera = await _make_camera(app)
    FakeBlinkService.next_error = BlinkAuthError("token expired")
    response = await admin_client.post(f"/api/cameras/{camera.id}/live-view/start")
    assert response.status_code == 401


async def test_start_live_view_maps_unsupported_camera_to_409(
    admin_client: AsyncClient, app: FastAPI
) -> None:
    _install_fake_manager(app)
    camera = await _make_camera(app)
    FakeBlinkService.next_error = LiveViewUnsupportedError("rtsps:// only")
    response = await admin_client.post(f"/api/cameras/{camera.id}/live-view/start")
    assert response.status_code == 409


async def test_start_live_view_maps_generic_blink_errors_to_502(
    admin_client: AsyncClient, app: FastAPI
) -> None:
    _install_fake_manager(app)
    camera = await _make_camera(app)
    FakeBlinkService.next_error = BlinkError("camera offline")
    response = await admin_client.post(f"/api/cameras/{camera.id}/live-view/start")
    assert response.status_code == 502


async def test_start_live_view_maps_manager_start_errors_to_502(
    admin_client: AsyncClient, app: FastAPI
) -> None:
    manager = _install_fake_manager(app)
    manager.next_error = LiveViewStartError("ffmpeg is not installed")
    camera = await _make_camera(app)
    response = await admin_client.post(f"/api/cameras/{camera.id}/live-view/start")
    assert response.status_code == 502


async def test_stop_live_view_requires_authentication(client: AsyncClient, app: FastAPI) -> None:
    _install_fake_manager(app)
    camera = await _make_camera(app)
    response = await client.post(f"/api/cameras/{camera.id}/live-view/{uuid.uuid4()}/stop")
    assert response.status_code == 401


async def test_stop_live_view_requires_superuser(viewer_client: AsyncClient, app: FastAPI) -> None:
    _install_fake_manager(app)
    camera = await _make_camera(app)
    response = await viewer_client.post(f"/api/cameras/{camera.id}/live-view/{uuid.uuid4()}/stop")
    assert response.status_code == 403


async def test_stop_live_view_stops_a_known_session(
    admin_client: AsyncClient, app: FastAPI
) -> None:
    manager = _install_fake_manager(app)
    camera = await _make_camera(app)
    start = await admin_client.post(f"/api/cameras/{camera.id}/live-view/start")
    session_id = uuid.UUID(start.json()["session_id"])

    response = await admin_client.post(f"/api/cameras/{camera.id}/live-view/{session_id}/stop")

    assert response.status_code == 204
    assert manager.stop_calls == [session_id]


async def test_stop_live_view_is_a_no_op_for_an_unknown_session(
    admin_client: AsyncClient, app: FastAPI
) -> None:
    manager = _install_fake_manager(app)
    camera = await _make_camera(app)
    response = await admin_client.post(f"/api/cameras/{camera.id}/live-view/{uuid.uuid4()}/stop")
    assert response.status_code == 204
    assert manager.stop_calls == []


async def test_stop_live_view_is_a_no_op_when_the_session_belongs_to_another_camera(
    admin_client: AsyncClient, app: FastAPI
) -> None:
    manager = _install_fake_manager(app)
    camera_a = await _make_camera(app, name="Camera A")
    camera_b = await _make_camera(app, name="Camera B")
    start = await admin_client.post(f"/api/cameras/{camera_a.id}/live-view/start")
    session_id = start.json()["session_id"]

    response = await admin_client.post(f"/api/cameras/{camera_b.id}/live-view/{session_id}/stop")

    assert response.status_code == 204
    assert manager.stop_calls == []


async def test_get_live_view_file_requires_authentication(
    client: AsyncClient, app: FastAPI
) -> None:
    _install_fake_manager(app)
    camera = await _make_camera(app)
    response = await client.get(f"/api/cameras/{camera.id}/live-view/{uuid.uuid4()}/stream.m3u8")
    assert response.status_code == 401


async def test_get_live_view_file_allowed_for_a_viewer(
    viewer_client: AsyncClient, app: FastAPI, tmp_path: Path
) -> None:
    # admin_client and viewer_client share one cookie jar when both are
    # requested by the same test (see viewer_client's docstring in
    # conftest.py) - seeding the fake manager's session directly sidesteps
    # needing a real admin-authenticated start call here.
    manager = _install_fake_manager(app)
    camera = await _make_camera(app)
    session_id = uuid.uuid4()
    manager.sessions[session_id] = _FakeSession(session_id=session_id, camera_id=camera.id)
    playlist = tmp_path / "stream.m3u8"
    playlist.write_text("#EXTM3U\n")
    manager.file_to_serve = playlist

    response = await viewer_client.get(
        f"/api/cameras/{camera.id}/live-view/{session_id}/stream.m3u8"
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/vnd.apple.mpegurl"
    assert response.headers["cache-control"] == "no-store"


async def test_get_live_view_file_serves_a_segment_with_the_right_content_type(
    admin_client: AsyncClient, app: FastAPI, tmp_path: Path
) -> None:
    manager = _install_fake_manager(app)
    camera = await _make_camera(app)
    start = await admin_client.post(f"/api/cameras/{camera.id}/live-view/start")
    session_id = start.json()["session_id"]
    segment = tmp_path / "segment00001.ts"
    segment.write_bytes(b"ts-bytes")
    manager.file_to_serve = segment

    response = await admin_client.get(
        f"/api/cameras/{camera.id}/live-view/{session_id}/segment00001.ts"
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "video/mp2t"


async def test_get_live_view_file_404s_for_an_unknown_session(
    admin_client: AsyncClient, app: FastAPI
) -> None:
    _install_fake_manager(app)
    camera = await _make_camera(app)
    response = await admin_client.get(
        f"/api/cameras/{camera.id}/live-view/{uuid.uuid4()}/stream.m3u8"
    )
    assert response.status_code == 404


async def test_get_live_view_file_404s_when_the_session_belongs_to_another_camera(
    admin_client: AsyncClient, app: FastAPI
) -> None:
    _install_fake_manager(app)
    camera_a = await _make_camera(app, name="Camera A")
    camera_b = await _make_camera(app, name="Camera B")
    start = await admin_client.post(f"/api/cameras/{camera_a.id}/live-view/start")
    session_id = start.json()["session_id"]

    response = await admin_client.get(
        f"/api/cameras/{camera_b.id}/live-view/{session_id}/stream.m3u8"
    )

    assert response.status_code == 404


async def test_get_live_view_file_404s_when_the_manager_has_no_file_yet(
    admin_client: AsyncClient, app: FastAPI
) -> None:
    manager = _install_fake_manager(app)
    camera = await _make_camera(app)
    start = await admin_client.post(f"/api/cameras/{camera.id}/live-view/start")
    session_id = start.json()["session_id"]
    manager.file_to_serve = None

    response = await admin_client.get(
        f"/api/cameras/{camera.id}/live-view/{session_id}/stream.m3u8"
    )

    assert response.status_code == 404
