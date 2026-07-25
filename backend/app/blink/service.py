"""The application-facing Blink contract.

The real blinkpy-backed implementation lands with the Blink-integration
feature; the foundation ships the contract plus a null object so every caller
is written against the seam from day one.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


class BlinkError(Exception):
    """Base class for Blink integration failures."""


class BlinkAuthError(BlinkError):
    """Credentials rejected or 2FA required/failed."""


class BlinkNotConfiguredError(BlinkError):
    """No Blink account has been linked yet."""


@dataclass(frozen=True, slots=True)
class BlinkCameraInfo:
    camera_id: str
    network_id: str
    name: str
    camera_type: str
    battery: str | None
    thumbnail_url: str | None
    enabled: bool


@dataclass(frozen=True, slots=True)
class BlinkMediaItem:
    media_id: str
    camera_name: str
    network_id: str
    created_at: datetime
    media_url: str | None
    thumbnail_url: str | None
    deleted: bool


class BlinkService(Protocol):
    async def authenticate(self, username: str, password: str) -> dict[str, Any]:
        """Log in and return the token blob to persist (encrypted)."""
        ...

    async def get_cameras(self) -> list[BlinkCameraInfo]: ...

    async def list_media(self, since: datetime | None = None) -> list[BlinkMediaItem]: ...

    async def download_media(self, item: BlinkMediaItem) -> bytes: ...

    async def close(self) -> None: ...


class NullBlinkService:
    """Stands in until a Blink account is linked."""

    async def authenticate(self, username: str, password: str) -> dict[str, Any]:
        raise BlinkNotConfiguredError

    async def get_cameras(self) -> list[BlinkCameraInfo]:
        raise BlinkNotConfiguredError

    async def list_media(self, since: datetime | None = None) -> list[BlinkMediaItem]:
        raise BlinkNotConfiguredError

    async def download_media(self, item: BlinkMediaItem) -> bytes:
        raise BlinkNotConfiguredError

    async def close(self) -> None:
        return None


def get_blink_service() -> BlinkService:
    return NullBlinkService()
