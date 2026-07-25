"""The Blink seam: null object behavior and DTO immutability."""

import dataclasses
from datetime import UTC, datetime

import pytest

from app.blink.service import (
    BlinkAuthError,
    BlinkCameraInfo,
    BlinkError,
    BlinkMediaItem,
    BlinkNotConfiguredError,
    NullBlinkService,
    get_blink_service,
)


def test_factory_returns_null_service_until_configured() -> None:
    assert isinstance(get_blink_service(), NullBlinkService)


async def test_null_service_raises_not_configured() -> None:
    service = NullBlinkService()
    with pytest.raises(BlinkNotConfiguredError):
        await service.authenticate("user", "pass")
    with pytest.raises(BlinkNotConfiguredError):
        await service.get_cameras()
    with pytest.raises(BlinkNotConfiguredError):
        await service.list_media()
    item = BlinkMediaItem(
        media_id="1",
        camera_name="Front Door",
        network_id="n1",
        created_at=datetime.now(UTC),
        media_url=None,
        thumbnail_url=None,
        deleted=False,
    )
    with pytest.raises(BlinkNotConfiguredError):
        await service.download_media(item)
    assert await service.close() is None


def test_error_hierarchy() -> None:
    assert issubclass(BlinkAuthError, BlinkError)
    assert issubclass(BlinkNotConfiguredError, BlinkError)


def test_dtos_are_frozen() -> None:
    camera = BlinkCameraInfo(
        camera_id="c1",
        network_id="n1",
        name="Driveway",
        camera_type="catalina",
        battery="ok",
        thumbnail_url=None,
        enabled=True,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        camera.name = "Garage"  # type: ignore[misc]
