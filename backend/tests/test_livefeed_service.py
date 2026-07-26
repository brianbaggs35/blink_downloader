"""Live View / Security Feed settings, and the shared camera-preview fetch.

BlinkPyService is faked (patched at the name imported into
app.livefeed.service), matching test_worker_download.py's convention.
"""

# pytest calls autouse fixtures implicitly; pyright can't see that usage.
# pyright: reportUnusedFunction=false

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.blink.models import BlinkAccount, BlinkAccountStatus, Camera
from app.blink.service import BlinkAuthError, BlinkError
from app.config import get_settings
from app.livefeed.schemas import (
    LiveViewSettingsUpdate,
    SecurityFeedSettingsUpdate,
)
from app.livefeed.service import (
    get_camera_preview,
    get_live_view_settings,
    get_security_feed_settings,
    record_camera_clip,
    update_live_view_settings,
    update_security_feed_settings,
)
from app.security.crypto import SecretBox
from app.storage.service import get_clip_storage


class FakeBlinkService:
    next_preview: ClassVar[bytes] = b"preview-bytes"
    next_snap: ClassVar[bytes] = b"snapshot-bytes"
    next_error: ClassVar[Exception | None] = None
    calls: ClassVar[list[str]] = []
    instances: ClassVar[list[FakeBlinkService]] = []

    def __init__(self, token_data: dict[str, Any]) -> None:
        self.token_data_in = dict(token_data)
        self.closed = False
        FakeBlinkService.instances.append(self)

    async def get_camera_preview(self, camera_id: str) -> bytes:
        del camera_id
        FakeBlinkService.calls.append("preview")
        if FakeBlinkService.next_error:
            raise FakeBlinkService.next_error
        return FakeBlinkService.next_preview

    async def snap_camera_picture(self, camera_id: str) -> bytes:
        del camera_id
        FakeBlinkService.calls.append("snap")
        if FakeBlinkService.next_error:
            raise FakeBlinkService.next_error
        return FakeBlinkService.next_snap

    async def record_clip(self, camera_id: str) -> None:
        del camera_id
        FakeBlinkService.calls.append("record")
        if FakeBlinkService.next_error:
            raise FakeBlinkService.next_error

    async def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_fake_service(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeBlinkService.instances = []
    FakeBlinkService.calls = []
    FakeBlinkService.next_error = None
    FakeBlinkService.next_preview = b"preview-bytes"
    FakeBlinkService.next_snap = b"snapshot-bytes"
    monkeypatch.setattr("app.livefeed.service.BlinkPyService", FakeBlinkService)


async def _make_account_and_camera(session: AsyncSession) -> tuple[BlinkAccount, Camera]:
    box = SecretBox(get_settings().encryption_key)
    account = BlinkAccount(
        encrypted_username=box.encrypt("brian@example.com"),
        encrypted_password=box.encrypt("hunter2"),
        encrypted_token_data=box.encrypt(json.dumps({"refresh_token": "r"})),
    )
    session.add(account)
    await session.flush()
    camera = Camera(
        blink_account_id=account.id,
        blink_camera_id="cam-1",
        blink_network_id="net-1",
        name="Front Door",
        camera_type="catalina",
    )
    session.add(camera)
    await session.commit()
    await session.refresh(account)
    await session.refresh(camera)
    return account, camera


# --------------------------------------------------------------- settings


async def test_live_view_settings_defaults_on_first_access(app_session: AsyncSession) -> None:
    row = await get_live_view_settings(app_session)
    assert row.default_camera_id is None
    assert row.auto_refresh_enabled is False
    assert row.auto_refresh_interval_seconds == 10


async def test_live_view_settings_update_persists(app_session: AsyncSession) -> None:
    _account, camera = await _make_account_and_camera(app_session)
    await update_live_view_settings(
        app_session,
        LiveViewSettingsUpdate(
            default_camera_id=camera.id, auto_refresh_enabled=True, auto_refresh_interval_seconds=30
        ),
    )
    row = await get_live_view_settings(app_session)
    assert row.default_camera_id == camera.id
    assert row.auto_refresh_enabled is True
    assert row.auto_refresh_interval_seconds == 30


async def test_security_feed_settings_defaults_on_first_access(app_session: AsyncSession) -> None:
    row = await get_security_feed_settings(app_session)
    assert row.camera_ids == []
    assert row.columns == 2
    assert row.refresh_interval_seconds == 20


async def test_security_feed_settings_update_persists(app_session: AsyncSession) -> None:
    _account, camera = await _make_account_and_camera(app_session)
    await update_security_feed_settings(
        app_session,
        SecurityFeedSettingsUpdate(camera_ids=[camera.id], columns=3, refresh_interval_seconds=45),
    )
    row = await get_security_feed_settings(app_session)
    assert row.camera_ids == [str(camera.id)]
    assert row.columns == 3
    assert row.refresh_interval_seconds == 45


# ---------------------------------------------------------- camera preview


async def test_get_camera_preview_fetches_and_caches(
    app_session: AsyncSession, tmp_path: Path
) -> None:
    _account, camera = await _make_account_and_camera(app_session)
    storage = get_clip_storage(tmp_path)

    path = await get_camera_preview(app_session, get_settings(), camera, storage, force=False)
    assert path.read_bytes() == b"preview-bytes"
    assert FakeBlinkService.calls == ["preview"]
    await app_session.refresh(camera)
    assert camera.preview_path == str(path)
    assert camera.preview_updated_at is not None


async def test_get_camera_preview_serves_the_cache_when_fresh(
    app_session: AsyncSession, tmp_path: Path
) -> None:
    _account, camera = await _make_account_and_camera(app_session)
    storage = get_clip_storage(tmp_path)

    await get_camera_preview(app_session, get_settings(), camera, storage, force=False)
    assert FakeBlinkService.calls == ["preview"]

    # A second passive fetch immediately after should hit the cache, not Blink.
    await get_camera_preview(app_session, get_settings(), camera, storage, force=False)
    assert FakeBlinkService.calls == ["preview"]


async def test_get_camera_preview_refetches_once_stale(
    app_session: AsyncSession, tmp_path: Path
) -> None:
    _account, camera = await _make_account_and_camera(app_session)
    storage = get_clip_storage(tmp_path)
    await get_camera_preview(app_session, get_settings(), camera, storage, force=False)

    camera.preview_updated_at = datetime.now(UTC) - timedelta(minutes=5)
    await app_session.commit()

    await get_camera_preview(app_session, get_settings(), camera, storage, force=False)
    assert FakeBlinkService.calls == ["preview", "preview"]


async def test_get_camera_preview_refetches_if_the_cached_file_vanished(
    app_session: AsyncSession, tmp_path: Path
) -> None:
    _account, camera = await _make_account_and_camera(app_session)
    storage = get_clip_storage(tmp_path)
    path = await get_camera_preview(app_session, get_settings(), camera, storage, force=False)
    path.unlink()

    await get_camera_preview(app_session, get_settings(), camera, storage, force=False)
    assert FakeBlinkService.calls == ["preview", "preview"]


async def test_get_camera_preview_force_always_snaps_even_when_fresh(
    app_session: AsyncSession, tmp_path: Path
) -> None:
    _account, camera = await _make_account_and_camera(app_session)
    storage = get_clip_storage(tmp_path)
    await get_camera_preview(app_session, get_settings(), camera, storage, force=False)

    path = await get_camera_preview(app_session, get_settings(), camera, storage, force=True)
    assert FakeBlinkService.calls == ["preview", "snap"]
    assert path.read_bytes() == b"snapshot-bytes"


async def test_get_camera_preview_marks_account_error_on_auth_failure(
    app_session: AsyncSession, tmp_path: Path
) -> None:
    account, camera = await _make_account_and_camera(app_session)
    storage = get_clip_storage(tmp_path)
    FakeBlinkService.next_error = BlinkAuthError("token expired")

    with pytest.raises(BlinkAuthError):
        await get_camera_preview(app_session, get_settings(), camera, storage, force=False)

    await app_session.refresh(account)
    assert account.status == BlinkAccountStatus.ERROR
    assert account.last_error == "token expired"


async def test_get_camera_preview_propagates_generic_blink_errors(
    app_session: AsyncSession, tmp_path: Path
) -> None:
    _account, camera = await _make_account_and_camera(app_session)
    storage = get_clip_storage(tmp_path)
    FakeBlinkService.next_error = BlinkError("camera offline")

    with pytest.raises(BlinkError):
        await get_camera_preview(app_session, get_settings(), camera, storage, force=False)


# ------------------------------------------------------------------ record


async def test_record_camera_clip_calls_the_service(app_session: AsyncSession) -> None:
    _account, camera = await _make_account_and_camera(app_session)
    await record_camera_clip(app_session, get_settings(), camera)
    assert FakeBlinkService.calls == ["record"]


async def test_record_camera_clip_marks_account_error_on_auth_failure(
    app_session: AsyncSession,
) -> None:
    account, camera = await _make_account_and_camera(app_session)
    FakeBlinkService.next_error = BlinkAuthError("token expired")

    with pytest.raises(BlinkAuthError):
        await record_camera_clip(app_session, get_settings(), camera)

    await app_session.refresh(account)
    assert account.status == BlinkAccountStatus.ERROR
