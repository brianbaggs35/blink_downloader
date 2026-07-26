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
    fresh. Raises BlinkError/BlinkAuthError on failure - the caller (the
    API layer) maps those to an HTTP response."""
    if not force and _is_fresh(camera):
        return Path(camera.preview_path)  # type: ignore[arg-type]  — guarded by _is_fresh

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
