"""The application-facing Blink contract, backed by blinkpy.

A :class:`BlinkService` is constructed from an already-valid token blob
(``blink_accounts.token_data``, decrypted) and only ever performs
already-authenticated operations. Establishing that token blob in the first
place — including the interactive 2FA step — is a separate, stateful concern
handled by :mod:`app.blink.linker`.
"""

# blinkpy ships no type stubs (no py.typed marker); every value that
# round-trips through it comes back Unknown to the type checker.
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownVariableType=false

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from aiohttp import ClientResponseError
from blinkpy.auth import Auth, LoginError, TokenRefreshFailed, UnauthorizedError
from blinkpy.blinkpy import Blink, BlinkSetupError


class BlinkError(Exception):
    """Base class for Blink integration failures."""


class BlinkAuthError(BlinkError):
    """The stored token is no longer valid; the account must be re-linked."""


@dataclass(frozen=True, slots=True)
class BlinkCameraInfo:
    camera_id: str
    network_id: str
    name: str
    camera_type: str
    battery: str | None
    thumbnail_path: str | None
    motion_enabled: bool


@dataclass(frozen=True, slots=True)
class BlinkMediaItem:
    """One entry from Blink's media-changed feed."""

    media_id: str
    """Stable dedup key — the media resource path Blink assigns the clip."""
    camera_name: str
    created_at: datetime
    deleted: bool
    raw: dict[str, Any]


class BlinkService(Protocol):
    async def get_cameras(self) -> list[BlinkCameraInfo]: ...

    async def list_media(self, since: datetime | None = None) -> list[BlinkMediaItem]: ...

    async def download_media(self, item: BlinkMediaItem) -> bytes:
        """Fetch the raw bytes for a clip returned by :meth:`list_media`."""
        ...

    @property
    def token_data(self) -> dict[str, Any]:
        """Current auth state to persist — tokens rotate on refresh."""
        ...

    async def close(self) -> None: ...


def _parse_created_at(value: str) -> datetime:
    # Blink emits ISO-8601 timestamps; fall back to "now" only if the feed
    # ever sends something unparseable rather than dropping the clip.
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(UTC)


class BlinkPyService:
    """Adapter over blinkpy's ``Auth``/``Blink`` pair.

    ``full`` startup (auth + homescreen + camera/network setup) is only
    needed for camera/media listing; a plain clip download only needs a
    valid auth header and the base URL, so it skips the extra API calls.
    """

    def __init__(self, token_data: dict[str, Any]) -> None:
        self._auth = Auth(login_data=dict(token_data), no_prompt=True)
        self._blink = Blink(session=self._auth.session)
        self._blink.auth = self._auth
        self._started_full = False
        self._started_light = False

    async def _ensure_light(self) -> None:
        if self._started_light or self._started_full:
            return
        try:
            await self._auth.startup()
        except (LoginError, TokenRefreshFailed, UnauthorizedError) as exc:
            raise BlinkAuthError(str(exc)) from exc
        self._blink.setup_urls()
        self._started_light = True

    async def _ensure_full(self) -> None:
        if self._started_full:
            return
        await self._ensure_light()
        try:
            await self._blink.get_homescreen()
        except (BlinkSetupError, ClientResponseError) as exc:
            raise BlinkAuthError(str(exc)) from exc
        self._started_full = True

    async def get_cameras(self) -> list[BlinkCameraInfo]:
        await self._ensure_full()
        cameras: list[BlinkCameraInfo] = []
        for camera in self._blink.cameras.values():
            attrs = camera.attributes
            cameras.append(
                BlinkCameraInfo(
                    camera_id=str(attrs["camera_id"]),
                    network_id=str(attrs["network_id"]),
                    name=str(attrs["name"]),
                    camera_type=str(attrs["type"]),
                    battery=attrs.get("battery"),
                    thumbnail_path=attrs.get("thumbnail"),
                    motion_enabled=bool(attrs.get("motion_enabled", False)),
                )
            )
        return cameras

    async def list_media(self, since: datetime | None = None) -> list[BlinkMediaItem]:
        await self._ensure_full()
        since_str = since.strftime("%Y/%m/%d %H:%M:%S") if since else None
        try:
            raw_items = await self._blink.get_videos_metadata(since=since_str)
        except ClientResponseError as exc:
            raise BlinkAuthError(str(exc)) from exc

        items: list[BlinkMediaItem] = []
        for raw in raw_items:
            try:
                media_id = str(raw["media"])
                camera_name = str(raw["device_name"])
                created_at = _parse_created_at(str(raw["created_at"]))
                deleted = bool(raw["deleted"])
            except KeyError:
                continue
            items.append(
                BlinkMediaItem(
                    media_id=media_id,
                    camera_name=camera_name,
                    created_at=created_at,
                    deleted=deleted,
                    raw=raw,
                )
            )
        return items

    async def download_media(self, item: BlinkMediaItem) -> bytes:
        await self._ensure_light()
        try:
            response = await self._blink.do_http_get(item.media_id)
        except ClientResponseError as exc:
            raise BlinkAuthError(str(exc)) from exc
        return await response.read()

    @property
    def token_data(self) -> dict[str, Any]:
        return dict(self._auth.login_attributes)

    async def close(self) -> None:
        await self._auth.session.close()


def get_blink_service(token_data: dict[str, Any]) -> BlinkService:
    return BlinkPyService(token_data)
