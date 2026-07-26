"""BlinkPyService: adapter logic over blinkpy's Auth/Blink pair.

Fakes stand in for blinkpy's ``Auth``/``Blink`` classes (patched at the names
imported into ``app.blink.service``) so this exercises *our* orchestration
and error-mapping logic without depending on blinkpy's internals or any real
network call.
"""

# pytest calls autouse fixtures implicitly; pyright can't see that usage.
# pyright: reportUnusedFunction=false

from datetime import UTC, datetime
from typing import Any, ClassVar
from unittest.mock import AsyncMock, Mock

import pytest
from aiohttp import ClientResponseError, RequestInfo
from yarl import URL

from app.blink.service import (
    BlinkAuthError,
    BlinkCameraInfo,
    BlinkError,
    BlinkMediaItem,
    BlinkPyService,
    CameraNotFoundError,
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
    def __init__(self, attrs: dict[str, Any]) -> None:
        self.attributes = attrs
        self.camera_id = attrs.get("camera_id")
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
        self.setup_urls = Mock()  # real Blink.setup_urls() is synchronous
        self.get_homescreen = AsyncMock()
        self.homescreen_error: Exception | None = None
        self.media_items: list[dict[str, Any]] = []
        self.media_error: Exception | None = None
        self.http_get_error: Exception | None = None
        self.last_http_get_address: str | None = None
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
