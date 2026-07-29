"""/api/sync-modules/*: viewing is available to any signed-in household
member; arming, motion toggling, and local-storage download/delete are
admin-only, matching every other "changes real device state" action.

BlinkPyService is faked at the name imported into app.sync_module.service -
same convention as test_sync_module_service.py.
"""

# pytest calls autouse fixtures implicitly; pyright can't see that usage.
# pyright: reportUnusedFunction=false

import json
import uuid
from datetime import UTC, datetime
from typing import Any, ClassVar

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.blink.models import BlinkAccount, Camera
from app.blink.service import BlinkError
from app.config import get_settings
from app.security.crypto import SecretBox
from app.sync_module.models import SyncModule, SyncModuleLocalItem
from tests.conftest import PlainSettings


class FakeBlinkService:
    next_error: ClassVar[Exception | None] = None
    instances: ClassVar[list[FakeBlinkService]] = []

    def __init__(self, token_data: dict[str, Any]) -> None:
        self.token_data_in = dict(token_data)
        self.closed = False
        FakeBlinkService.instances.append(self)

    async def set_sync_module_arm(self, network_id: str, armed: bool) -> None:
        del network_id, armed
        if FakeBlinkService.next_error:
            raise FakeBlinkService.next_error

    async def set_camera_motion_detection(
        self, network_id: str, camera_id: str, motion_bucket: str, enabled: bool
    ) -> None:
        del network_id, camera_id, motion_bucket, enabled
        if FakeBlinkService.next_error:
            raise FakeBlinkService.next_error

    async def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_fake_service(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeBlinkService.instances = []
    FakeBlinkService.next_error = None
    monkeypatch.setattr("app.sync_module.service.BlinkPyService", FakeBlinkService)


async def _make_account(app: FastAPI) -> BlinkAccount:
    async with app.state.sessionmaker() as session:
        box = SecretBox(get_settings().encryption_key)
        account = BlinkAccount(
            encrypted_username=box.encrypt("u"),
            encrypted_password=box.encrypt("p"),
            encrypted_token_data=box.encrypt(json.dumps({"refresh_token": "r"})),
        )
        session.add(account)
        await session.commit()
        await session.refresh(account)
        return account


async def _make_camera(
    app: FastAPI, account: BlinkAccount, *, name: str = "Front Door", mini: bool = False
) -> Camera:
    async with app.state.sessionmaker() as session:
        camera = Camera(
            blink_account_id=account.id,
            blink_camera_id=f"cam-{name}",
            blink_network_id="net-1",
            name=name,
            camera_type="catalina" if not mini else "owl",
            motion_action_type="mini" if mini else "default",
        )
        session.add(camera)
        await session.commit()
        await session.refresh(camera)
        return camera


async def _make_sync_module(app: FastAPI, account: BlinkAccount) -> SyncModule:
    async with app.state.sessionmaker() as session:
        sync_module = SyncModule(
            blink_account_id=account.id,
            network_id="net-1",
            sync_id="sync-1",
            name="Home",
            is_physical_hub=True,
            online=True,
            local_storage_compatible=True,
            local_storage_enabled=True,
            local_storage_active=True,
            local_storage_manifest_id="m-1",
        )
        session.add(sync_module)
        await session.commit()
        await session.refresh(sync_module)
        return sync_module


async def _make_local_item(app: FastAPI, sync_module: SyncModule) -> SyncModuleLocalItem:
    async with app.state.sessionmaker() as session:
        item = SyncModuleLocalItem(
            sync_module_id=sync_module.id,
            camera_name="Front Door",
            blink_item_id=1,
            recorded_at=datetime.now(UTC),
            size_bytes=1024,
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)
        return item


# ---------------------------------------------------------------------- list


async def test_list_requires_authentication(client: AsyncClient) -> None:
    assert (await client.get("/api/sync-modules")).status_code == 401


async def test_list_is_empty_with_no_sync_modules(admin_client: AsyncClient) -> None:
    response = await admin_client.get("/api/sync-modules")
    assert response.status_code == 200
    assert response.json() == []


async def test_list_includes_camera_count(admin_client: AsyncClient, app: FastAPI) -> None:
    account = await _make_account(app)
    await _make_sync_module(app, account)
    await _make_camera(app, account)
    await _make_camera(app, account, name="Backyard")

    response = await admin_client.get("/api/sync-modules")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["camera_count"] == 2
    assert body[0]["name"] == "Home"


async def test_viewer_can_list(viewer_client: AsyncClient) -> None:
    assert (await viewer_client.get("/api/sync-modules")).status_code == 200


# ------------------------------------------------------------------- cameras


async def test_list_cameras_404_for_unknown_sync_module(admin_client: AsyncClient) -> None:
    response = await admin_client.get(f"/api/sync-modules/{uuid.uuid4()}/cameras")
    assert response.status_code == 404


async def test_list_cameras_reports_motion_support(admin_client: AsyncClient, app: FastAPI) -> None:
    account = await _make_account(app)
    sync_module = await _make_sync_module(app, account)
    await _make_camera(app, account, name="Front Door")
    await _make_camera(app, account, name="Mini", mini=True)

    response = await admin_client.get(f"/api/sync-modules/{sync_module.id}/cameras")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    by_name = {camera["name"]: camera for camera in body}
    assert by_name["Front Door"]["motion_supported"] is True
    assert by_name["Mini"]["motion_supported"] is False


# ----------------------------------------------------------------------- arm


async def test_arm_requires_admin(viewer_client: AsyncClient, app: FastAPI) -> None:
    account = await _make_account(app)
    sync_module = await _make_sync_module(app, account)
    response = await viewer_client.post(
        f"/api/sync-modules/{sync_module.id}/arm", json={"armed": True}
    )
    assert response.status_code == 403


async def test_arm_404_for_unknown_sync_module(admin_client: AsyncClient) -> None:
    response = await admin_client.post(
        f"/api/sync-modules/{uuid.uuid4()}/arm", json={"armed": True}
    )
    assert response.status_code == 404


async def test_arm_succeeds(admin_client: AsyncClient, app: FastAPI) -> None:
    account = await _make_account(app)
    sync_module = await _make_sync_module(app, account)
    response = await admin_client.post(
        f"/api/sync-modules/{sync_module.id}/arm", json={"armed": False}
    )
    assert response.status_code == 200
    assert response.json()["armed"] is False


async def test_arm_maps_blink_errors_to_502(admin_client: AsyncClient, app: FastAPI) -> None:
    account = await _make_account(app)
    sync_module = await _make_sync_module(app, account)
    FakeBlinkService.next_error = BlinkError("device offline")
    response = await admin_client.post(
        f"/api/sync-modules/{sync_module.id}/arm", json={"armed": True}
    )
    assert response.status_code == 502


# --------------------------------------------------------------- motion one


async def test_set_motion_requires_admin(viewer_client: AsyncClient, app: FastAPI) -> None:
    account = await _make_account(app)
    sync_module = await _make_sync_module(app, account)
    camera = await _make_camera(app, account)
    response = await viewer_client.patch(
        f"/api/sync-modules/{sync_module.id}/cameras/{camera.id}/motion", json={"enabled": True}
    )
    assert response.status_code == 403


async def test_set_motion_404_for_unknown_camera(admin_client: AsyncClient, app: FastAPI) -> None:
    account = await _make_account(app)
    sync_module = await _make_sync_module(app, account)
    # A real (non-matching) camera present - not zero cameras - so the
    # lookup actually iterates past one entry before exhausting, rather
    # than trivially skipping an empty list.
    await _make_camera(app, account, name="Other")
    response = await admin_client.patch(
        f"/api/sync-modules/{sync_module.id}/cameras/{uuid.uuid4()}/motion",
        json={"enabled": True},
    )
    assert response.status_code == 404


async def test_set_motion_succeeds(admin_client: AsyncClient, app: FastAPI) -> None:
    account = await _make_account(app)
    sync_module = await _make_sync_module(app, account)
    camera = await _make_camera(app, account)
    response = await admin_client.patch(
        f"/api/sync-modules/{sync_module.id}/cameras/{camera.id}/motion", json={"enabled": False}
    )
    assert response.status_code == 200
    assert response.json()["motion_enabled"] is False


async def test_set_motion_409_for_a_mini(admin_client: AsyncClient, app: FastAPI) -> None:
    account = await _make_account(app)
    sync_module = await _make_sync_module(app, account)
    mini = await _make_camera(app, account, name="Mini", mini=True)
    response = await admin_client.patch(
        f"/api/sync-modules/{sync_module.id}/cameras/{mini.id}/motion", json={"enabled": True}
    )
    assert response.status_code == 409


async def test_set_motion_maps_blink_errors_to_502(admin_client: AsyncClient, app: FastAPI) -> None:
    account = await _make_account(app)
    sync_module = await _make_sync_module(app, account)
    camera = await _make_camera(app, account)
    FakeBlinkService.next_error = BlinkError("camera offline")
    response = await admin_client.patch(
        f"/api/sync-modules/{sync_module.id}/cameras/{camera.id}/motion", json={"enabled": True}
    )
    assert response.status_code == 502


# -------------------------------------------------------------- motion bulk


async def test_bulk_set_motion_requires_admin(viewer_client: AsyncClient, app: FastAPI) -> None:
    account = await _make_account(app)
    sync_module = await _make_sync_module(app, account)
    response = await viewer_client.patch(
        f"/api/sync-modules/{sync_module.id}/cameras/motion", json={"enabled": True}
    )
    assert response.status_code == 403


async def test_bulk_set_motion_succeeds(admin_client: AsyncClient, app: FastAPI) -> None:
    account = await _make_account(app)
    sync_module = await _make_sync_module(app, account)
    await _make_camera(app, account, name="Front Door")
    await _make_camera(app, account, name="Backyard")
    await _make_camera(app, account, name="Mini", mini=True)

    response = await admin_client.patch(
        f"/api/sync-modules/{sync_module.id}/cameras/motion", json={"enabled": True}
    )
    assert response.status_code == 200
    assert response.json() == {"succeeded": 2, "failed": 0}


async def test_bulk_set_motion_maps_blink_errors_to_502(
    admin_client: AsyncClient, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Per-camera BlinkError/BlinkAuthError failures are swallowed into the
    # failed count (see bulk_set_camera_motion_detection), so the only way
    # the route's own except BlinkError branch is reachable is a failure
    # before the per-camera loop starts - disable_blink_network_calls.
    account = await _make_account(app)
    sync_module = await _make_sync_module(app, account)
    await _make_camera(app, account, name="Front Door")
    monkeypatch.setattr(
        "app.api.sync_modules.get_settings",
        lambda: PlainSettings(disable_blink_network_calls=True),
    )

    response = await admin_client.patch(
        f"/api/sync-modules/{sync_module.id}/cameras/motion", json={"enabled": True}
    )
    assert response.status_code == 502


# --------------------------------------------------------------- local storage


async def test_list_local_storage_items(admin_client: AsyncClient, app: FastAPI) -> None:
    account = await _make_account(app)
    sync_module = await _make_sync_module(app, account)
    await _make_local_item(app, sync_module)

    response = await admin_client.get(f"/api/sync-modules/{sync_module.id}/local-storage/items")
    assert response.status_code == 200
    assert len(response.json()) == 1


async def test_refresh_local_storage_requires_admin(
    viewer_client: AsyncClient, app: FastAPI
) -> None:
    account = await _make_account(app)
    sync_module = await _make_sync_module(app, account)
    response = await viewer_client.post(f"/api/sync-modules/{sync_module.id}/local-storage/refresh")
    assert response.status_code == 403


async def test_refresh_local_storage_enqueues_a_job(
    admin_client: AsyncClient, app: FastAPI
) -> None:
    account = await _make_account(app)
    sync_module = await _make_sync_module(app, account)
    response = await admin_client.post(f"/api/sync-modules/{sync_module.id}/local-storage/refresh")
    assert response.status_code == 202


async def test_download_local_storage_item_404_for_unknown_item(
    admin_client: AsyncClient, app: FastAPI
) -> None:
    account = await _make_account(app)
    sync_module = await _make_sync_module(app, account)
    # A real (non-matching) item present, not zero items - see
    # test_set_motion_404_for_unknown_camera's comment for why.
    await _make_local_item(app, sync_module)
    response = await admin_client.post(
        f"/api/sync-modules/{sync_module.id}/local-storage/items/{uuid.uuid4()}/download"
    )
    assert response.status_code == 404


async def test_download_local_storage_item_enqueues_a_job(
    admin_client: AsyncClient, app: FastAPI
) -> None:
    account = await _make_account(app)
    sync_module = await _make_sync_module(app, account)
    item = await _make_local_item(app, sync_module)
    response = await admin_client.post(
        f"/api/sync-modules/{sync_module.id}/local-storage/items/{item.id}/download"
    )
    assert response.status_code == 202


async def test_delete_local_storage_item_requires_admin(
    viewer_client: AsyncClient, app: FastAPI
) -> None:
    account = await _make_account(app)
    sync_module = await _make_sync_module(app, account)
    item = await _make_local_item(app, sync_module)
    response = await viewer_client.delete(
        f"/api/sync-modules/{sync_module.id}/local-storage/items/{item.id}"
    )
    assert response.status_code == 403


async def test_delete_local_storage_item_enqueues_a_job(
    admin_client: AsyncClient, app: FastAPI
) -> None:
    account = await _make_account(app)
    sync_module = await _make_sync_module(app, account)
    item = await _make_local_item(app, sync_module)
    response = await admin_client.delete(
        f"/api/sync-modules/{sync_module.id}/local-storage/items/{item.id}"
    )
    assert response.status_code == 202


async def test_get_local_storage_item_file_404_when_not_downloaded(
    admin_client: AsyncClient, app: FastAPI
) -> None:
    account = await _make_account(app)
    sync_module = await _make_sync_module(app, account)
    item = await _make_local_item(app, sync_module)
    response = await admin_client.get(
        f"/api/sync-modules/{sync_module.id}/local-storage/items/{item.id}/file"
    )
    assert response.status_code == 404


async def test_get_local_storage_item_file_404_for_unknown_item(
    admin_client: AsyncClient, app: FastAPI
) -> None:
    account = await _make_account(app)
    sync_module = await _make_sync_module(app, account)
    # A real (non-matching) item present, not zero items - see
    # test_set_motion_404_for_unknown_camera's comment for why.
    await _make_local_item(app, sync_module)
    response = await admin_client.get(
        f"/api/sync-modules/{sync_module.id}/local-storage/items/{uuid.uuid4()}/file"
    )
    assert response.status_code == 404


async def test_get_local_storage_item_file_serves_the_downloaded_file(
    admin_client: AsyncClient, app: FastAPI, tmp_path: Any
) -> None:
    account = await _make_account(app)
    sync_module = await _make_sync_module(app, account)
    item = await _make_local_item(app, sync_module)
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"clip-bytes")
    async with app.state.sessionmaker() as session:
        row = await session.get(SyncModuleLocalItem, item.id)
        assert row is not None
        row.storage_path = str(path)
        await session.commit()

    response = await admin_client.get(
        f"/api/sync-modules/{sync_module.id}/local-storage/items/{item.id}/file"
    )
    assert response.status_code == 200
    assert response.content == b"clip-bytes"
