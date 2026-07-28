"""Live View / Security Feed settings, and the shared camera-preview fetch
these two features are both built on.

A "preview" is a single still image - see app/livefeed/models.py for why
(no browser-playable live stream exists through blinkpy). Two fetch modes:
passive (whatever Blink last captured - a real motion event or an earlier
snap) and forced (wakes the camera for a fresh capture right now). Passive
fetches are cached to local disk and only re-requested from Blink once
PREVIEW_FRESHNESS_SECONDS has passed, so N browser tabs polling the same
camera cost one upstream request, not N.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.blink.models import BlinkAccount, BlinkAccountStatus, Camera
from app.blink.service import BlinkAuthError, BlinkError, BlinkPyService
from app.config import Settings
from app.livefeed.models import SINGLETON_ID, LiveViewSettings, SecurityFeedSettings
from app.livefeed.schemas import (
    LiveViewSettingsUpdate,
    SecurityFeedSettingsUpdate,
)
from app.security.crypto import SecretBox
from app.storage.service import ClipStorage

PREVIEW_FRESHNESS_SECONDS = 8


async def get_live_view_settings(session: AsyncSession) -> LiveViewSettings:
    row = await session.get(LiveViewSettings, SINGLETON_ID)
    if row is None:
        row = LiveViewSettings(id=SINGLETON_ID)
        session.add(row)
        await session.flush()
    return row


async def update_live_view_settings(
    session: AsyncSession, payload: LiveViewSettingsUpdate
) -> LiveViewSettings:
    row = await get_live_view_settings(session)
    row.default_camera_id = payload.default_camera_id
    row.auto_refresh_enabled = payload.auto_refresh_enabled
    row.auto_refresh_interval_seconds = payload.auto_refresh_interval_seconds
    await session.commit()
    await session.refresh(row)
    return row


async def get_security_feed_settings(session: AsyncSession) -> SecurityFeedSettings:
    row = await session.get(SecurityFeedSettings, SINGLETON_ID)
    if row is None:
        row = SecurityFeedSettings(id=SINGLETON_ID)
        session.add(row)
        await session.flush()
    return row


async def update_security_feed_settings(
    session: AsyncSession, payload: SecurityFeedSettingsUpdate
) -> SecurityFeedSettings:
    row = await get_security_feed_settings(session)
    row.camera_ids = [str(camera_id) for camera_id in payload.camera_ids]
    row.columns = payload.columns
    row.refresh_interval_seconds = payload.refresh_interval_seconds
    await session.commit()
    await session.refresh(row)
    return row


def _is_fresh(camera: Camera) -> bool:
    if not camera.preview_path or camera.preview_updated_at is None:
        return False
    if not Path(camera.preview_path).exists():
        return False
    age = datetime.now(UTC) - camera.preview_updated_at
    return age < timedelta(seconds=PREVIEW_FRESHNESS_SECONDS)


def _stale_cache(camera: Camera, *, force: bool) -> Path | None:
    """A cached file that's past PREVIEW_FRESHNESS_SECONDS but still real -
    usable as a last resort when a live refetch fails, for a passive request."""
    if force or not camera.preview_path:
        return None
    path = Path(camera.preview_path)
    return path if path.exists() else None


async def get_camera_preview(
    session: AsyncSession,
    settings: Settings,
    camera: Camera,
    storage: ClipStorage,
    *,
    force: bool,
) -> Path:
    """Returns the local path to a preview image for ``camera``, fetching a
    fresh one from Blink first unless a recent passive fetch is still
    fresh. A passive request (force=False) that fails to refetch falls back
    to a stale cached file rather than erroring, if one exists; a forced
    request always surfaces the real failure. Raises BlinkError/BlinkAuthError
    when there's truly nothing to show - the caller (the API layer) maps
    those to an HTTP response."""
    if not force and _is_fresh(camera):
        return Path(camera.preview_path)  # type: ignore[arg-type]  — guarded by _is_fresh

    if settings.disable_blink_network_calls:
        # No real Blink account exists to actually refresh from (see
        # Settings.disable_blink_network_calls) - regardless of force or
        # freshness, the seeded cache (present for every camera) is the only
        # image that will ever exist. force=False here is deliberate (not a
        # passthrough of the real `force` param): _stale_cache's own
        # force-means-"never use a cached file" rule doesn't apply to this
        # disabled-network-calls path.
        cached = _stale_cache(camera, force=False)
        if cached is not None:
            return cached
        raise BlinkError("No cached preview available, and live Blink calls are disabled.")

    account = await session.get(BlinkAccount, camera.blink_account_id)
    if account is None:  # pragma: no cover — FK guarantees this can't happen
        raise BlinkError("No Blink account linked.")

    box = SecretBox(settings.encryption_key)
    token_data = json.loads(box.decrypt(account.encrypted_token_data))
    service = BlinkPyService(token_data)
    try:
        image = (
            await service.snap_camera_picture(camera.blink_camera_id)
            if force
            else await service.get_camera_preview(camera.blink_camera_id)
        )
    except BlinkAuthError as exc:
        account.status = BlinkAccountStatus.ERROR
        account.last_error = str(exc)
        await session.commit()
        stale = _stale_cache(camera, force=force)
        if stale is not None:
            return stale
        raise
    except BlinkError:
        # A passive poll degrades to "whatever we last had" rather than a
        # broken image the moment Blink is briefly unreachable - force=True
        # is an explicit "capture right now" ask, so it still surfaces the
        # real failure instead of silently handing back a stale frame.
        stale = _stale_cache(camera, force=force)
        if stale is not None:
            return stale
        raise
    finally:
        await service.close()

    path = storage.camera_preview_path(camera.id)
    await storage.write(path, image)
    camera.preview_path = str(path)
    camera.preview_updated_at = datetime.now(UTC)
    await session.commit()
    return path


async def record_camera_clip(session: AsyncSession, settings: Settings, camera: Camera) -> None:
    if settings.disable_blink_network_calls:
        # No real Blink account exists to actually record against (see
        # Settings.disable_blink_network_calls) - raises the same class of
        # error a real failure would (exercising the same request/response
        # wiring live_view.spec.ts's "saving a clip surfaces the outcome as
        # a toast" already expects), but - unlike a real failure - never
        # touches the shared account row, so it can't corrupt the "healthy"
        # status every other e2e test also reads.
        raise BlinkError("Live Blink calls are disabled in this environment.")

    account = await session.get(BlinkAccount, camera.blink_account_id)
    if account is None:  # pragma: no cover — FK guarantees this can't happen
        raise BlinkError("No Blink account linked.")

    box = SecretBox(settings.encryption_key)
    token_data = json.loads(box.decrypt(account.encrypted_token_data))
    service = BlinkPyService(token_data)
    try:
        await service.record_clip(camera.blink_camera_id)
    except BlinkAuthError as exc:
        account.status = BlinkAccountStatus.ERROR
        account.last_error = str(exc)
        await session.commit()
        raise
    finally:
        await service.close()
