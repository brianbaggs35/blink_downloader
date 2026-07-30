"""The application-facing Blink contract, backed by blinkpy.

A :class:`BlinkService` is constructed from an already-valid token blob
(``blink_accounts.token_data``, decrypted) and only ever performs
already-authenticated operations. Establishing that token blob in the first
place — including the interactive 2FA step — is a separate, stateful concern
handled by :mod:`app.blink.linker`.
"""

# blinkpy ships no type stubs (no py.typed marker); every value that
# round-trips through it comes back Unknown to the type checker.
# pyright: reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownVariableType=false

import string
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from aiohttp import ClientResponseError
from blinkpy import api
from blinkpy.auth import Auth, LoginError, TokenRefreshFailed, UnauthorizedError
from blinkpy.blinkpy import Blink, BlinkSetupError
from blinkpy.helpers.util import local_storage_clip_url_template
from blinkpy.sync_module import BlinkLotus, BlinkOwl


class BlinkError(Exception):
    """Base class for Blink integration failures."""


class BlinkAuthError(BlinkError):
    """The stored token is no longer valid; the account must be re-linked."""


class CameraNotFoundError(BlinkError):
    """No camera with this id exists on the linked Blink account."""


class SyncModuleNotFoundError(BlinkError):
    """No sync module with this network id exists on the linked Blink account."""


class LocalStorageUnavailableError(BlinkError):
    """This network has no active local (USB) storage to browse - either it
    has no physical Sync Module (a Mini/Doorbell-only "sync-less" network) or
    its Sync Module doesn't support/have local storage enabled."""


@dataclass(frozen=True, slots=True)
class BlinkCameraInfo:
    camera_id: str
    network_id: str
    name: str
    camera_type: str
    battery: str | None
    thumbnail_path: str | None
    motion_enabled: bool
    motion_action_type: str
    """blinkpy's own "default"/"mini"/"doorbell" dispatch bucket for this
    camera's motion-detection endpoint - not the same thing as camera_type
    above (the raw Blink product codename, e.g. "catalina")."""


@dataclass(frozen=True, slots=True)
class BlinkMediaItem:
    """One entry from Blink's media-changed feed."""

    media_id: str
    """Stable dedup key — the media resource path Blink assigns the clip."""
    camera_name: str
    created_at: datetime
    deleted: bool
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class BlinkSyncModuleInfo:
    network_id: str
    sync_id: str | None
    name: str
    serial: str | None
    firmware_version: str | None
    armed: bool | None
    """None means blinkpy itself couldn't determine arm state (network info
    unavailable) - never coerced to False, which would misreport an unknown
    state as "disarmed"."""
    online: bool
    is_physical_hub: bool
    """False for a "sync-less" network (Mini-only or Doorbell-only, with no
    physical Sync Module) - see blinkpy's BlinkOwl/BlinkLotus."""
    local_storage_compatible: bool
    local_storage_enabled: bool
    local_storage_active: bool


@dataclass(frozen=True, slots=True)
class BlinkLocalStorageItem:
    """One entry from a Sync Module's local (USB) storage manifest."""

    item_id: int
    camera_name: str
    recorded_at: datetime
    size_bytes: int


@dataclass(frozen=True, slots=True)
class BlinkLocalStorageManifest:
    manifest_id: str
    items: list[BlinkLocalStorageItem]


class BlinkService(Protocol):
    async def get_cameras(self) -> list[BlinkCameraInfo]: ...

    async def list_media(self, since: datetime | None = None) -> list[BlinkMediaItem]: ...

    async def download_media(self, item: BlinkMediaItem) -> bytes:
        """Fetch the raw bytes for a clip returned by :meth:`list_media`."""
        ...

    async def get_camera_preview(self, camera_id: str) -> bytes:
        """The camera's current thumbnail, whatever Blink last captured
        (a real motion event or a prior snapshot/snap_picture call) - never
        triggers a new capture itself."""
        ...

    async def snap_camera_picture(self, camera_id: str) -> bytes:
        """Force the camera to take a fresh picture right now and return
        it. Wakes a battery-powered camera - use for an explicit user
        action (Live View's refresh button), not a passive poll loop."""
        ...

    async def record_clip(self, camera_id: str) -> None:
        """Trigger an on-demand clip recording. The resulting clip arrives
        through the normal sync/download pipeline, not returned here."""
        ...

    async def get_sync_modules(self) -> list[BlinkSyncModuleInfo]: ...

    async def set_sync_module_arm(self, network_id: str, armed: bool) -> None: ...

    async def set_camera_motion_detection(
        self, network_id: str, camera_id: str, motion_bucket: str, enabled: bool
    ) -> None: ...

    async def refresh_local_storage_manifest(self, network_id: str) -> BlinkLocalStorageManifest:
        """Raises LocalStorageUnavailableError if this network has no active
        local storage to browse."""
        ...

    async def prepare_local_storage_clip(
        self, network_id: str, sync_id: str, manifest_id: str, item_id: int
    ) -> None:
        """Pushes the clip from the Sync Module's USB drive up to Blink's
        cloud servers - required before download_local_storage_clip can
        fetch it. Slow (polls internally); callers should treat this as a
        background operation, not an instant one."""
        ...

    async def download_local_storage_clip(
        self, network_id: str, sync_id: str, manifest_id: str, item_id: int
    ) -> bytes:
        """Fetches the already-prepared clip's bytes."""
        ...

    async def delete_local_storage_clip(
        self, network_id: str, sync_id: str, manifest_id: str, item_id: int
    ) -> bool:
        """Deletes the clip from the Sync Module's local storage. Does not
        require prepare_local_storage_clip to have run first."""
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

    ``full`` startup (auth + homescreen) is enough for clip listing/download,
    which only need a valid auth header and the base URL. Camera lookup needs
    the heavier ``sync`` startup instead: blinkpy only ever populates
    ``Blink.cameras`` inside ``setup_post_verify()`` (``Blink.__init__`` starts
    it as an empty dict, and ``get_homescreen()`` never touches it) - so
    anything that reads ``self._blink.cameras`` must go through
    ``_ensure_sync()``, not ``_ensure_full()`` alone.
    """

    def __init__(self, token_data: dict[str, Any]) -> None:
        self._auth = Auth(login_data=dict(token_data), no_prompt=True)
        self._blink = Blink(session=self._auth.session)
        self._blink.auth = self._auth
        self._started_full = False
        self._started_light = False
        self._started_sync = False

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

    async def _ensure_sync(self) -> None:
        """Populates self._blink.sync/.cameras via blinkpy's full
        setup_post_verify() flow - needed for sync-module/local-storage
        features, and for get_cameras()/_find_camera() (see the class
        docstring): _ensure_full() alone never populates self._blink.cameras,
        it only fetches the homescreen."""
        if self._started_sync:
            return
        await self._ensure_full()
        try:
            initialized = await self._blink.setup_post_verify()
        except ClientResponseError as exc:
            raise BlinkAuthError(str(exc)) from exc
        if not initialized:
            raise BlinkError("Could not initialize Blink sync modules.")
        self._started_sync = True

    def _find_sync_module(self, network_id: str) -> Any:
        for sync_module in self._blink.sync.values():
            if str(sync_module.network_id) == network_id:
                return sync_module
        raise SyncModuleNotFoundError(f"No sync module with network id {network_id}.")

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
                    # camera.camera_type (the instance attribute, not attrs
                    # above) is blinkpy's own dispatch bucket - it has no key
                    # in the attributes dict at all.
                    motion_action_type=str(camera.camera_type) or "default",
                )
            )
        return cameras

    # blinkpy's own default (`stop=10`, ~25 items/page) silently truncates at
    # ~225 items with no error - fine for its CLI use case, not for a sync
    # that must never silently drop clips on a busy first backfill. There's
    # no uncapped option, so ask for enough pages that any real backlog fits.
    _MEDIA_PAGE_STOP = 500

    async def list_media(self, since: datetime | None = None) -> list[BlinkMediaItem]:
        await self._ensure_full()
        since_str = since.strftime("%Y/%m/%d %H:%M:%S") if since else None
        try:
            raw_items = await self._blink.get_videos_metadata(
                since=since_str, stop=self._MEDIA_PAGE_STOP
            )
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

    async def _find_camera(self, camera_id: str) -> Any:
        await self._ensure_full()
        for camera in self._blink.cameras.values():
            # By stable camera_id, never by dict key/name - blinkpy indexes
            # self._blink.cameras by display name, which two cameras on one
            # account can share (see docs/ARCHITECTURE.md#blink-integration).
            if str(camera.camera_id) == camera_id:
                return camera
        raise CameraNotFoundError(f"No camera with id {camera_id} on this Blink account.")

    async def get_camera_preview(self, camera_id: str) -> bytes:
        camera = await self._find_camera(camera_id)
        try:
            response = await camera.get_thumbnail()
        except ClientResponseError as exc:
            raise BlinkAuthError(str(exc)) from exc
        if response is None:
            raise BlinkError(f"Camera {camera_id} has no thumbnail available yet.")
        return await response.read()

    async def snap_camera_picture(self, camera_id: str) -> bytes:
        camera = await self._find_camera(camera_id)
        try:
            await camera.snap_picture()
        except ClientResponseError as exc:
            raise BlinkAuthError(str(exc)) from exc
        image = camera.image_from_cache
        if not image:
            raise BlinkError(f"Camera {camera_id} did not return an image.")
        return bytes(image)

    async def record_clip(self, camera_id: str) -> None:
        camera = await self._find_camera(camera_id)
        try:
            await camera.record()
        except ClientResponseError as exc:
            raise BlinkAuthError(str(exc)) from exc

    async def get_sync_modules(self) -> list[BlinkSyncModuleInfo]:
        await self._ensure_sync()
        modules: list[BlinkSyncModuleInfo] = []
        for sync_module in self._blink.sync.values():
            # Reaches into blinkpy's underscore-prefixed _local_storage dict
            # deliberately - it has no public accessor for these flags (only
            # the derived .local_storage bool, which collapses "compatible",
            # "enabled", and "active" into one value we need to show
            # separately).
            local_storage = sync_module._local_storage
            modules.append(
                BlinkSyncModuleInfo(
                    network_id=str(sync_module.network_id),
                    sync_id=str(sync_module.sync_id) if sync_module.sync_id is not None else None,
                    name=str(sync_module.name),
                    serial=sync_module.serial,
                    firmware_version=sync_module.version,
                    armed=sync_module.arm,
                    online=bool(sync_module.online),
                    is_physical_hub=not isinstance(sync_module, (BlinkOwl, BlinkLotus)),
                    local_storage_compatible=bool(local_storage["compatible"]),
                    local_storage_enabled=bool(local_storage["enabled"]),
                    local_storage_active=bool(sync_module.local_storage),
                )
            )
        return modules

    async def set_sync_module_arm(self, network_id: str, armed: bool) -> None:
        await self._ensure_light()
        try:
            if armed:
                await api.request_system_arm(self._blink, network_id)
            else:
                await api.request_system_disarm(self._blink, network_id)
        except ClientResponseError as exc:
            raise BlinkAuthError(str(exc)) from exc

    async def set_camera_motion_detection(
        self, network_id: str, camera_id: str, motion_bucket: str, enabled: bool
    ) -> None:
        await self._ensure_light()
        try:
            if enabled:
                await api.request_motion_detection_enable(
                    self._blink, network_id, camera_id, camera_type=motion_bucket
                )
            else:
                await api.request_motion_detection_disable(
                    self._blink, network_id, camera_id, camera_type=motion_bucket
                )
        except ClientResponseError as exc:
            raise BlinkAuthError(str(exc)) from exc

    async def refresh_local_storage_manifest(self, network_id: str) -> BlinkLocalStorageManifest:
        await self._ensure_sync()
        sync_module = self._find_sync_module(network_id)
        is_physical_hub = not isinstance(sync_module, (BlinkOwl, BlinkLotus))
        # Reaches into _local_storage - see get_sync_modules' comment above.
        if not is_physical_hub or not sync_module._local_storage["compatible"]:
            raise LocalStorageUnavailableError(
                f"Network {network_id} has no local (USB) storage to browse."
            )
        try:
            await sync_module.update_local_storage_manifest()
        except ClientResponseError as exc:
            raise BlinkAuthError(str(exc)) from exc
        local_storage = sync_module._local_storage
        if local_storage["manifest_stale"]:
            raise BlinkError(f"Could not refresh the local storage manifest for {network_id}.")
        items = [
            BlinkLocalStorageItem(
                item_id=item.id,
                camera_name=item.name,
                recorded_at=item.created_at,
                size_bytes=int(item.size),
            )
            for item in local_storage["manifest"]
        ]
        manifest_id = str(local_storage["last_manifest_id"])
        return BlinkLocalStorageManifest(manifest_id=manifest_id, items=items)

    async def prepare_local_storage_clip(
        self, network_id: str, sync_id: str, manifest_id: str, item_id: int
    ) -> None:
        await self._ensure_light()
        try:
            await api.request_local_storage_clip(
                self._blink, network_id, sync_id, manifest_id, item_id
            )
        except ClientResponseError as exc:
            raise BlinkAuthError(str(exc)) from exc

    def _local_storage_clip_url(
        self, network_id: str, sync_id: str, manifest_id: str, item_id: int
    ) -> str:
        path = string.Template(local_storage_clip_url_template()).substitute(
            account_id=self._blink.account_id,
            network_id=network_id,
            sync_id=sync_id,
            manifest_id=manifest_id,
            clip_id=item_id,
        )
        # _ensure_light() (called by every caller of this method) always
        # runs setup_urls() first, so .urls is never actually None here -
        # blinkpy just has no stubs for pyright to see that guarantee.
        return str(self._blink.urls.base_url) + path  # pyright: ignore[reportOptionalMemberAccess]

    async def download_local_storage_clip(
        self, network_id: str, sync_id: str, manifest_id: str, item_id: int
    ) -> bytes:
        await self._ensure_light()
        url = self._local_storage_clip_url(network_id, sync_id, manifest_id, item_id)
        try:
            response = await api.http_get(self._blink, url, json=False)
        except ClientResponseError as exc:
            raise BlinkAuthError(str(exc)) from exc
        return await response.read()

    async def delete_local_storage_clip(
        self, network_id: str, sync_id: str, manifest_id: str, item_id: int
    ) -> bool:
        await self._ensure_light()
        # Same URL prepare/download use, with "request" swapped for "delete"
        # - mirrors blinkpy's own LocalStorageMediaItem.delete_video.
        url = self._local_storage_clip_url(network_id, sync_id, manifest_id, item_id).replace(
            "request", "delete"
        )
        try:
            response = await api.http_post(self._blink, url, json=False)
        except ClientResponseError as exc:
            raise BlinkAuthError(str(exc)) from exc
        return bool(response.status == 200)

    @property
    def token_data(self) -> dict[str, Any]:
        return dict(self._auth.login_attributes)

    async def close(self) -> None:
        await self._auth.session.close()


def get_blink_service(token_data: dict[str, Any]) -> BlinkService:
    return BlinkPyService(token_data)
