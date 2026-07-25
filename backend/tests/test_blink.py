"""BlinkPyService: adapter logic over blinkpy's Auth/Blink pair.

Fakes stand in for blinkpy's ``Auth``/``Blink`` classes (patched at the names
imported into ``app.blink.service``) so this exercises *our* orchestration
and error-mapping logic without depending on blinkpy's internals or any real
network call.
"""

from datetime import UTC, datetime
from typing import Any
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


class FakeAuth:
    instances: list["FakeAuth"] = []

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
    instances: list["FakeBlink"] = []

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

    async def get_videos_metadata(self, since: Any = None) -> list[dict[str, Any]]:
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
