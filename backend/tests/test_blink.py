"""BlinkPyService: adapter logic over blinkpy's Auth/Blink pair.

Fakes stand in for blinkpy's ``Auth``/``Blink`` classes (patched at the names
imported into ``app.blink.service``) so this exercises *our* orchestration
and error-mapping logic without depending on blinkpy's internals or any real
network call.
"""

# pytest calls autouse fixtures implicitly; pyright can't see that usage.
# pyright: reportUnusedFunction=false
# blinkpy ships no type stubs (no py.typed marker) - same as app/blink/service.py.
# pyright: reportMissingTypeStubs=false

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, ClassVar
from unittest.mock import AsyncMock, Mock

import pytest
from aiohttp import ClientResponseError, RequestInfo
from blinkpy.sync_module import BlinkOwl
from yarl import URL

from app.blink.service import (
    BlinkAuthError,
    BlinkCameraInfo,
    BlinkError,
    BlinkLocalStorageItem,
    BlinkLocalStorageManifest,
    BlinkMediaItem,
    BlinkPyService,
    BlinkSyncModuleInfo,
    CameraNotFoundError,
    LocalStorageUnavailableError,
    SyncModuleNotFoundError,
    get_blink_service,
)

_FAKE_REQUEST_INFO = RequestInfo(
    url=URL("https://rest.immedia-semi.com/x"),
    method="GET",
    headers={},  # type: ignore[arg-type]
    real_url=URL("https://rest.immedia-semi.com/x"),
)


def _client_response_error(status: int) -> ClientResponseError:
    return ClientResponseError(_FAKE_REQUEST_INFO, (), status=status)


class FakeSession:
    def __init__(self) -> None:
        self.close = AsyncMock()


class FakeCamera:
    def __init__(self, attrs: dict[str, Any], camera_type: str = "default") -> None:
        self.attributes = attrs
        self.camera_id = attrs.get("camera_id")
        # blinkpy's own "default"/"mini"/"doorbell" dispatch bucket - not
        # the same as attrs["type"] (the raw product codename).
        self.camera_type = camera_type
        self.thumbnail_response: Any = None
        self.thumbnail_error: Exception | None = None
        self.snap_error: Exception | None = None
        self.record_error: Exception | None = None
        self.recorded = False
        self.cached_image: bytes | None = None

    async def get_thumbnail(self) -> Any:
        if self.thumbnail_error:
            raise self.thumbnail_error
        return self.thumbnail_response

    async def snap_picture(self) -> None:
        if self.snap_error:
            raise self.snap_error

    @property
    def image_from_cache(self) -> bytes | None:
        return self.cached_image

    async def record(self) -> None:
        if self.record_error:
            raise self.record_error
        self.recorded = True


class FakeManifestItem:
    def __init__(self, item_id: int, name: str, created_at: datetime, size: int) -> None:
        self.id = item_id
        self.name = name
        self.created_at = created_at
        self.size = size


class FakeSyncModule:
    """Duck-types blinkpy's BlinkSyncModule closely enough for our adapter -
    a real BlinkSyncModule needs a live Blink instance to construct, which
    this avoids. is_physical_hub relies on isinstance(_, (BlinkOwl,
    BlinkLotus)) though, which a plain object like this always fails (in the
    correct direction) - the one test that needs is_physical_hub=False
    constructs a real BlinkOwl instead (see below)."""

    def __init__(
        self,
        network_id: str,
        *,
        sync_id: str | None = "sync-1",
        name: str = "Home",
        serial: str | None = "SN123",
        version: str | None = "1.2.3",
        armed: bool | None = True,
        online: bool = True,
        local_storage_compatible: bool = True,
        local_storage_enabled: bool = True,
        local_storage_active: bool = True,
        manifest: list[FakeManifestItem] | None = None,
    ) -> None:
        self.network_id = network_id
        self.sync_id = sync_id
        self.name = name
        self.serial = serial
        self.version = version
        self.arm = armed
        self.online = online
        self._local_storage: dict[str, Any] = {
            "compatible": local_storage_compatible,
            "enabled": local_storage_enabled,
            "status": local_storage_active,
            "manifest_stale": False,
            "last_manifest_id": "manifest-1",
            "manifest": manifest or [],
        }
        self.update_local_storage_manifest = AsyncMock()

    @property
    def local_storage(self) -> bool:
        return bool(self._local_storage["status"])


class FakeAuth:
    instances: ClassVar[list[FakeAuth]] = []

    def __init__(self, login_data: dict[str, Any] | None = None, **_kwargs: Any) -> None:
        self.login_data = login_data or {}
        self.session = FakeSession()
        self.startup_error: Exception | None = None
        FakeAuth.instances.append(self)

    async def startup(self) -> None:
        if self.startup_error:
            raise self.startup_error

    @property
    def login_attributes(self) -> dict[str, Any]:
        return {**self.login_data, "token": "rotated-token"}


class FakeBlink:
    instances: ClassVar[list[FakeBlink]] = []

    def __init__(self, session: Any = None) -> None:
        self.session = session
        self.auth: FakeAuth | None = None
        self.cameras: dict[str, FakeCamera] = {}
        self.sync: dict[str, Any] = {}
        self.setup_urls = Mock()  # real Blink.setup_urls() is synchronous
        self.get_homescreen = AsyncMock()
        self.setup_post_verify = AsyncMock(return_value=True)
        self.homescreen_error: Exception | None = None
        self.media_items: list[dict[str, Any]] = []
        self.media_error: Exception | None = None
        self.http_get_error: Exception | None = None
        self.last_http_get_address: str | None = None
        self.account_id = "acct-1"
        self.urls = SimpleNamespace(base_url="https://rest.example.com")
        FakeBlink.instances.append(self)

    async def get_videos_metadata(self, since: Any = None, stop: int = 10) -> list[dict[str, Any]]:
        del stop
        if self.media_error:
            raise self.media_error
        return self.media_items

    async def do_http_get(self, address: str) -> Any:
        if self.http_get_error:
            raise self.http_get_error
        self.last_http_get_address = address
        response = AsyncMock()
        response.read = AsyncMock(return_value=b"video-bytes")
        return response


@pytest.fixture(autouse=True)
def _reset_fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeAuth.instances = []
    FakeBlink.instances = []
    monkeypatch.setattr("app.blink.service.Auth", FakeAuth)
    monkeypatch.setattr("app.blink.service.Blink", FakeBlink)


def _make_service(
    token_data: dict[str, Any] | None = None,
) -> tuple[BlinkPyService, FakeAuth, FakeBlink]:
    service = BlinkPyService(token_data or {"refresh_token": "r"})
    auth = FakeAuth.instances[-1]
    blink = FakeBlink.instances[-1]
    return service, auth, blink


def test_factory_returns_blinkpy_service() -> None:
    service = get_blink_service({"refresh_token": "r"})
    assert isinstance(service, BlinkPyService)


async def test_get_cameras_maps_attributes() -> None:
    service, _auth, blink = _make_service()
    blink.cameras = {
        "front door": FakeCamera(
            {
                "camera_id": "1",
                "network_id": "10",
                "name": "Front Door",
                "type": "catalina",
                "battery": "ok",
                "thumbnail": "/media/thumb1.jpg",
                "motion_enabled": True,
            }
        )
    }
    cameras = await service.get_cameras()
    assert cameras == [
        BlinkCameraInfo(
            camera_id="1",
            network_id="10",
            name="Front Door",
            camera_type="catalina",
            battery="ok",
            thumbnail_path="/media/thumb1.jpg",
            motion_enabled=True,
            motion_action_type="default",
        )
    ]
    blink.get_homescreen.assert_awaited_once()


async def test_get_cameras_defaults_missing_optional_fields() -> None:
    service, _auth, blink = _make_service()
    blink.cameras = {
        "mini": FakeCamera(
            {
                "camera_id": "2",
                "network_id": "10",
                "name": "Mini",
                "type": "owl",
                "battery": None,
                "thumbnail": None,
            }
        )
    }
    cameras = await service.get_cameras()
    assert cameras[0].motion_enabled is False


async def test_full_startup_only_happens_once(monkeypatch: pytest.MonkeyPatch) -> None:
    service, _auth, blink = _make_service()
    blink.cameras = {}
    await service.get_cameras()
    await service.get_cameras()
    blink.get_homescreen.assert_awaited_once()


async def test_list_media_maps_items_and_skips_incomplete() -> None:
    service, _auth, blink = _make_service()
    blink.media_items = [
        {
            "media": "/media/clip1.mp4",
            "device_name": "Front Door",
            "created_at": "2026-07-20T10:00:00Z",
            "deleted": False,
        },
        {"device_name": "missing media/created_at/deleted keys"},
    ]
    items = await service.list_media(since=datetime(2026, 7, 1, tzinfo=UTC))
    assert items == [
        BlinkMediaItem(
            media_id="/media/clip1.mp4",
            camera_name="Front Door",
            created_at=datetime(2026, 7, 20, 10, 0, tzinfo=UTC),
            deleted=False,
            raw=blink.media_items[0],
        )
    ]


async def test_list_media_falls_back_to_now_for_unparseable_timestamp() -> None:
    service, _auth, blink = _make_service()
    blink.media_items = [
        {"media": "/x.mp4", "device_name": "Cam", "created_at": "not-a-date", "deleted": False}
    ]
    items = await service.list_media()
    assert (datetime.now(UTC) - items[0].created_at).total_seconds() < 5


async def test_download_media_returns_bytes_via_light_startup() -> None:
    service, _auth, blink = _make_service()
    item = BlinkMediaItem(
        media_id="/media/clip1.mp4",
        camera_name="Front Door",
        created_at=datetime.now(UTC),
        deleted=False,
        raw={},
    )
    data = await service.download_media(item)
    assert data == b"video-bytes"
    assert blink.last_http_get_address == "/media/clip1.mp4"
    blink.get_homescreen.assert_not_awaited()  # light path, no full startup


async def test_download_media_does_not_repeat_light_startup_after_full() -> None:
    service, _auth, blink = _make_service()
    blink.cameras = {}
    await service.get_cameras()  # full startup
    item = BlinkMediaItem("m", "Cam", datetime.now(UTC), False, {})
    await service.download_media(item)
    blink.get_homescreen.assert_awaited_once()


@pytest.mark.parametrize(
    "exc_type",
    ["LoginError", "TokenRefreshFailed", "UnauthorizedError"],
)
async def test_startup_auth_failures_map_to_blink_auth_error(
    exc_type: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.blink.service as service_module

    service, auth, _blink = _make_service()
    exc_cls = getattr(service_module, exc_type)
    auth.startup_error = exc_cls("boom")
    with pytest.raises(BlinkAuthError):
        await service.get_cameras()


# ------------------------------------------------- preview / snapshot / record


def _put_camera(blink: FakeBlink, camera_id: str = "1", name: str = "front door") -> FakeCamera:
    camera = FakeCamera({"camera_id": camera_id, "network_id": "10", "name": name})
    blink.cameras = {name: camera}
    return camera


async def test_find_camera_raises_when_unknown() -> None:
    service, _auth, blink = _make_service()
    blink.cameras = {}
    with pytest.raises(CameraNotFoundError):
        await service.get_camera_preview("does-not-exist")


async def test_find_camera_looks_past_a_non_matching_camera() -> None:
    service, _auth, blink = _make_service()
    other = FakeCamera({"camera_id": "1", "network_id": "10", "name": "Other"})
    target = FakeCamera({"camera_id": "2", "network_id": "10", "name": "Target"})
    target.thumbnail_response = AsyncMock()
    target.thumbnail_response.read = AsyncMock(return_value=b"target-bytes")
    blink.cameras = {"other": other, "target": target}

    data = await service.get_camera_preview("2")
    assert data == b"target-bytes"


async def test_get_camera_preview_returns_thumbnail_bytes() -> None:
    service, _auth, blink = _make_service()
    camera = _put_camera(blink)
    response = AsyncMock()
    response.read = AsyncMock(return_value=b"thumbnail-bytes")
    camera.thumbnail_response = response

    data = await service.get_camera_preview("1")
    assert data == b"thumbnail-bytes"


async def test_get_camera_preview_raises_without_a_thumbnail() -> None:
    service, _auth, blink = _make_service()
    _put_camera(blink).thumbnail_response = None
    with pytest.raises(BlinkError):
        await service.get_camera_preview("1")


async def test_get_camera_preview_maps_auth_errors() -> None:
    service, _auth, blink = _make_service()
    _put_camera(blink).thumbnail_error = _client_response_error(401)
    with pytest.raises(BlinkAuthError):
        await service.get_camera_preview("1")


async def test_snap_camera_picture_returns_the_freshly_cached_image() -> None:
    service, _auth, blink = _make_service()
    camera = _put_camera(blink)
    camera.cached_image = b"fresh-snapshot"
    data = await service.snap_camera_picture("1")
    assert data == b"fresh-snapshot"


async def test_snap_camera_picture_raises_without_an_image() -> None:
    service, _auth, blink = _make_service()
    _put_camera(blink)
    with pytest.raises(BlinkError):
        await service.snap_camera_picture("1")


async def test_snap_camera_picture_maps_auth_errors() -> None:
    service, _auth, blink = _make_service()
    _put_camera(blink).snap_error = _client_response_error(401)
    with pytest.raises(BlinkAuthError):
        await service.snap_camera_picture("1")


async def test_record_clip_calls_the_camera() -> None:
    service, _auth, blink = _make_service()
    camera = _put_camera(blink)
    await service.record_clip("1")
    assert camera.recorded is True


async def test_record_clip_maps_auth_errors() -> None:
    service, _auth, blink = _make_service()
    _put_camera(blink).record_error = _client_response_error(401)
    with pytest.raises(BlinkAuthError):
        await service.record_clip("1")


async def test_homescreen_failure_maps_to_blink_auth_error() -> None:
    import app.blink.service as service_module

    service, _auth, blink = _make_service()
    blink.get_homescreen.side_effect = service_module.BlinkSetupError("nope")
    with pytest.raises(BlinkAuthError):
        await service.get_cameras()


async def test_list_media_client_response_error_maps_to_blink_auth_error() -> None:
    service, _auth, blink = _make_service()
    blink.cameras = {}
    blink.media_error = _client_response_error(401)
    with pytest.raises(BlinkAuthError):
        await service.list_media()


async def test_download_media_client_response_error_maps_to_blink_auth_error() -> None:
    service, _auth, blink = _make_service()
    blink.http_get_error = _client_response_error(401)
    item = BlinkMediaItem("m", "Cam", datetime.now(UTC), False, {})
    with pytest.raises(BlinkAuthError):
        await service.download_media(item)


async def test_token_data_reflects_rotated_tokens() -> None:
    service, _auth, _blink = _make_service({"refresh_token": "original"})
    assert service.token_data["token"] == "rotated-token"


async def test_close_closes_the_session() -> None:
    service, auth, _blink = _make_service()
    await service.close()
    auth.session.close.assert_awaited_once()


def test_error_hierarchy() -> None:
    assert issubclass(BlinkAuthError, BlinkError)
    assert issubclass(SyncModuleNotFoundError, BlinkError)
    assert issubclass(LocalStorageUnavailableError, BlinkError)


# --------------------------------------------------------------- sync modules


async def test_ensure_sync_only_calls_setup_post_verify_once() -> None:
    service, _auth, blink = _make_service()
    blink.sync = {}
    await service.get_sync_modules()
    await service.get_sync_modules()
    blink.setup_post_verify.assert_awaited_once()


async def test_ensure_sync_raises_when_setup_post_verify_returns_false() -> None:
    service, _auth, blink = _make_service()
    blink.setup_post_verify = AsyncMock(return_value=False)
    with pytest.raises(BlinkError):
        await service.get_sync_modules()


async def test_ensure_sync_maps_client_response_error() -> None:
    service, _auth, blink = _make_service()
    blink.setup_post_verify = AsyncMock(side_effect=_client_response_error(401))
    with pytest.raises(BlinkAuthError):
        await service.get_sync_modules()


async def test_get_sync_modules_maps_attributes() -> None:
    service, _auth, blink = _make_service()
    blink.sync = {
        "Home": FakeSyncModule(
            "10",
            sync_id="sync-1",
            name="Home",
            serial="SN123",
            version="2.1.0",
            armed=True,
            online=True,
            local_storage_compatible=True,
            local_storage_enabled=True,
            local_storage_active=True,
        )
    }
    modules = await service.get_sync_modules()
    assert modules == [
        BlinkSyncModuleInfo(
            network_id="10",
            sync_id="sync-1",
            name="Home",
            serial="SN123",
            firmware_version="2.1.0",
            armed=True,
            online=True,
            is_physical_hub=True,
            local_storage_compatible=True,
            local_storage_enabled=True,
            local_storage_active=True,
        )
    ]


async def test_get_sync_modules_surfaces_unknown_arm_state() -> None:
    service, _auth, blink = _make_service()
    blink.sync = {"Home": FakeSyncModule("10", armed=None)}
    modules = await service.get_sync_modules()
    assert modules[0].armed is None


async def test_get_sync_modules_handles_a_sync_id_of_none() -> None:
    service, _auth, blink = _make_service()
    blink.sync = {"Home": FakeSyncModule("10", sync_id=None)}
    modules = await service.get_sync_modules()
    assert modules[0].sync_id is None


async def test_get_sync_modules_is_physical_hub_false_for_a_sync_less_owl() -> None:
    service, _auth, blink = _make_service()
    owl_blink_stub = SimpleNamespace(
        auth=SimpleNamespace(region_id="us"), motion_interval=5, account_id="acct-1"
    )
    owl = BlinkOwl(
        owl_blink_stub, "Mini Network", "20", {"id": "owl-1", "serial": "SN-OWL", "enabled": True}
    )
    blink.sync = {"Mini Network": owl}
    modules = await service.get_sync_modules()
    assert modules[0].is_physical_hub is False
    assert modules[0].local_storage_compatible is False


def _minimal_attrs(camera_id: str) -> dict[str, Any]:
    return {"camera_id": camera_id, "network_id": "10", "name": "Cam", "type": "owl"}


async def test_get_cameras_reports_the_real_motion_action_type_bucket() -> None:
    service, _auth, blink = _make_service()
    blink.cameras = {"mini": FakeCamera(_minimal_attrs("2"), camera_type="mini")}
    cameras = await service.get_cameras()
    assert cameras[0].motion_action_type == "mini"


async def test_get_cameras_defaults_an_empty_motion_action_type_bucket() -> None:
    service, _auth, blink = _make_service()
    blink.cameras = {"cam": FakeCamera(_minimal_attrs("1"), camera_type="")}
    cameras = await service.get_cameras()
    assert cameras[0].motion_action_type == "default"


async def test_set_sync_module_arm_calls_request_system_arm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _auth, _blink = _make_service()
    mock_arm = AsyncMock()
    mock_disarm = AsyncMock()
    monkeypatch.setattr("app.blink.service.api.request_system_arm", mock_arm)
    monkeypatch.setattr("app.blink.service.api.request_system_disarm", mock_disarm)
    await service.set_sync_module_arm("10", True)
    mock_arm.assert_awaited_once()
    mock_disarm.assert_not_awaited()


async def test_set_sync_module_arm_calls_request_system_disarm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _auth, _blink = _make_service()
    mock_arm = AsyncMock()
    mock_disarm = AsyncMock()
    monkeypatch.setattr("app.blink.service.api.request_system_arm", mock_arm)
    monkeypatch.setattr("app.blink.service.api.request_system_disarm", mock_disarm)
    await service.set_sync_module_arm("10", False)
    mock_disarm.assert_awaited_once()
    mock_arm.assert_not_awaited()


async def test_set_sync_module_arm_maps_auth_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    service, _auth, _blink = _make_service()
    monkeypatch.setattr(
        "app.blink.service.api.request_system_arm",
        AsyncMock(side_effect=_client_response_error(401)),
    )
    with pytest.raises(BlinkAuthError):
        await service.set_sync_module_arm("10", True)


async def test_set_camera_motion_detection_calls_enable(monkeypatch: pytest.MonkeyPatch) -> None:
    service, _auth, blink = _make_service()
    mock_enable = AsyncMock()
    mock_disable = AsyncMock()
    monkeypatch.setattr("app.blink.service.api.request_motion_detection_enable", mock_enable)
    monkeypatch.setattr("app.blink.service.api.request_motion_detection_disable", mock_disable)
    await service.set_camera_motion_detection("10", "1", "default", True)
    mock_enable.assert_awaited_once_with(blink, "10", "1", camera_type="default")
    mock_disable.assert_not_awaited()


async def test_set_camera_motion_detection_calls_disable(monkeypatch: pytest.MonkeyPatch) -> None:
    service, _auth, blink = _make_service()
    mock_enable = AsyncMock()
    mock_disable = AsyncMock()
    monkeypatch.setattr("app.blink.service.api.request_motion_detection_enable", mock_enable)
    monkeypatch.setattr("app.blink.service.api.request_motion_detection_disable", mock_disable)
    await service.set_camera_motion_detection("10", "1", "mini", False)
    mock_disable.assert_awaited_once_with(blink, "10", "1", camera_type="mini")
    mock_enable.assert_not_awaited()


async def test_set_camera_motion_detection_maps_auth_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _auth, _blink = _make_service()
    monkeypatch.setattr(
        "app.blink.service.api.request_motion_detection_enable",
        AsyncMock(side_effect=_client_response_error(401)),
    )
    with pytest.raises(BlinkAuthError):
        await service.set_camera_motion_detection("10", "1", "default", True)


# --------------------------------------------------------- local storage (USB)


async def test_refresh_local_storage_manifest_returns_items() -> None:
    service, _auth, blink = _make_service()
    recorded_at = datetime(2026, 7, 20, 10, 0, tzinfo=UTC)
    blink.sync = {
        "Home": FakeSyncModule(
            "10", manifest=[FakeManifestItem(1, "Front Door", recorded_at, 1024)]
        )
    }
    manifest = await service.refresh_local_storage_manifest("10")
    assert manifest == BlinkLocalStorageManifest(
        manifest_id="manifest-1",
        items=[
            BlinkLocalStorageItem(
                item_id=1, camera_name="Front Door", recorded_at=recorded_at, size_bytes=1024
            )
        ],
    )


async def test_refresh_local_storage_manifest_raises_when_sync_module_not_found() -> None:
    service, _auth, blink = _make_service()
    # A non-matching sync module present (not an empty dict) - same
    # "keep looking, then exhaust" branch reasoning as the camera lookup
    # above.
    blink.sync = {"Other": FakeSyncModule("99")}
    with pytest.raises(SyncModuleNotFoundError):
        await service.refresh_local_storage_manifest("missing")


async def test_refresh_local_storage_manifest_raises_when_not_a_physical_hub() -> None:
    service, _auth, blink = _make_service()
    owl_blink_stub = SimpleNamespace(
        auth=SimpleNamespace(region_id="us"), motion_interval=5, account_id="acct-1"
    )
    owl = BlinkOwl(
        owl_blink_stub, "Mini Network", "20", {"id": "owl-1", "serial": "SN-OWL", "enabled": True}
    )
    blink.sync = {"Mini Network": owl}
    with pytest.raises(LocalStorageUnavailableError):
        await service.refresh_local_storage_manifest("20")


async def test_refresh_local_storage_manifest_raises_when_not_compatible() -> None:
    service, _auth, blink = _make_service()
    blink.sync = {"Home": FakeSyncModule("10", local_storage_compatible=False)}
    with pytest.raises(LocalStorageUnavailableError):
        await service.refresh_local_storage_manifest("10")


async def test_refresh_local_storage_manifest_raises_when_it_stays_stale() -> None:
    service, _auth, blink = _make_service()
    sync_module = FakeSyncModule("10")
    sync_module._local_storage["manifest_stale"] = True  # pyright: ignore[reportPrivateUsage]
    blink.sync = {"Home": sync_module}
    with pytest.raises(BlinkError):
        await service.refresh_local_storage_manifest("10")


async def test_refresh_local_storage_manifest_maps_auth_errors() -> None:
    service, _auth, blink = _make_service()
    sync_module = FakeSyncModule("10")
    sync_module.update_local_storage_manifest = AsyncMock(side_effect=_client_response_error(401))
    blink.sync = {"Home": sync_module}
    with pytest.raises(BlinkAuthError):
        await service.refresh_local_storage_manifest("10")


async def test_prepare_local_storage_clip_calls_the_api(monkeypatch: pytest.MonkeyPatch) -> None:
    service, _auth, blink = _make_service()
    mock_prepare = AsyncMock()
    monkeypatch.setattr("app.blink.service.api.request_local_storage_clip", mock_prepare)
    await service.prepare_local_storage_clip("10", "sync-1", "manifest-1", 42)
    mock_prepare.assert_awaited_once_with(blink, "10", "sync-1", "manifest-1", 42)


async def test_prepare_local_storage_clip_maps_auth_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    service, _auth, _blink = _make_service()
    monkeypatch.setattr(
        "app.blink.service.api.request_local_storage_clip",
        AsyncMock(side_effect=_client_response_error(401)),
    )
    with pytest.raises(BlinkAuthError):
        await service.prepare_local_storage_clip("10", "sync-1", "manifest-1", 42)


async def test_download_local_storage_clip_returns_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    service, _auth, _blink = _make_service()
    response = AsyncMock()
    response.read = AsyncMock(return_value=b"clip-bytes")
    monkeypatch.setattr("app.blink.service.api.http_get", AsyncMock(return_value=response))
    data = await service.download_local_storage_clip("10", "sync-1", "manifest-1", 42)
    assert data == b"clip-bytes"


async def test_download_local_storage_clip_maps_auth_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _auth, _blink = _make_service()
    monkeypatch.setattr(
        "app.blink.service.api.http_get", AsyncMock(side_effect=_client_response_error(401))
    )
    with pytest.raises(BlinkAuthError):
        await service.download_local_storage_clip("10", "sync-1", "manifest-1", 42)


async def test_delete_local_storage_clip_returns_true_on_200(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _auth, _blink = _make_service()
    response = Mock(status=200)
    monkeypatch.setattr("app.blink.service.api.http_post", AsyncMock(return_value=response))
    assert await service.delete_local_storage_clip("10", "sync-1", "manifest-1", 42) is True


async def test_delete_local_storage_clip_returns_false_on_non_200(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _auth, _blink = _make_service()
    response = Mock(status=500)
    monkeypatch.setattr("app.blink.service.api.http_post", AsyncMock(return_value=response))
    assert await service.delete_local_storage_clip("10", "sync-1", "manifest-1", 42) is False


async def test_delete_local_storage_clip_maps_auth_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    service, _auth, _blink = _make_service()
    monkeypatch.setattr(
        "app.blink.service.api.http_post", AsyncMock(side_effect=_client_response_error(401))
    )
    with pytest.raises(BlinkAuthError):
        await service.delete_local_storage_clip("10", "sync-1", "manifest-1", 42)
