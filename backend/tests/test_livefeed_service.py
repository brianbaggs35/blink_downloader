"""Live View / Security Feed settings, and the shared camera-preview fetch.

BlinkPyService is faked (patched at the name imported into
app.livefeed.service), matching test_worker_download.py's convention.
"""

# pytest calls autouse fixtures implicitly; pyright can't see that usage.
# pyright: reportUnusedFunction=false

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.blink.models import BlinkAccount, BlinkAccountStatus, Camera
from app.blink.service import (
    BlinkAuthError,
    BlinkError,
    BlinkLiveStreamHandle,
    LiveViewUnsupportedError,
)
from app.config import get_settings
from app.livefeed.live_stream import ClosableBlinkService, LiveViewSession, LiveViewStartError
from app.livefeed.schemas import (
    LiveViewSettingsUpdate,
    SecurityFeedSettingsUpdate,
)
from app.livefeed.service import (
    get_camera_preview,
    get_live_view_settings,
    get_security_feed_settings,
    record_camera_clip,
    start_live_view,
    update_live_view_settings,
    update_security_feed_settings,
)
from app.security.crypto import SecretBox, generate_key
from app.storage.service import get_clip_storage
from tests.conftest import PlainSettings


class FakeBlinkService:
    next_preview: ClassVar[bytes] = b"preview-bytes"
    next_snap: ClassVar[bytes] = b"snapshot-bytes"
    next_handle: ClassVar[Any] = None
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

    async def init_live_stream(self, camera_id: str) -> Any:
        del camera_id
        FakeBlinkService.calls.append("live_stream")
        if FakeBlinkService.next_error:
            raise FakeBlinkService.next_error
        return FakeBlinkService.next_handle

    async def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_fake_service(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeBlinkService.instances = []
    FakeBlinkService.calls = []
    FakeBlinkService.next_error = None
    FakeBlinkService.next_preview = b"preview-bytes"
    FakeBlinkService.next_snap = b"snapshot-bytes"
    FakeBlinkService.next_handle = None
    monkeypatch.setattr("app.livefeed.service.BlinkPyService", FakeBlinkService)


class FakeLiveViewManager:
    def __init__(self) -> None:
        self.calls: list[tuple[uuid.UUID, ClosableBlinkService, BlinkLiveStreamHandle]] = []
        self.next_error: Exception | None = None
        self.next_result: LiveViewSession = cast("LiveViewSession", object())

    async def start_session(
        self, camera_id: uuid.UUID, service: ClosableBlinkService, handle: BlinkLiveStreamHandle
    ) -> LiveViewSession:
        self.calls.append((camera_id, service, handle))
        if self.next_error:
            raise self.next_error
        return self.next_result


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


async def _make_account_with_undecryptable_token(
    session: AsyncSession,
) -> tuple[BlinkAccount, Camera]:
    """encrypted_token_data is ciphertext from a *different* key than the
    one this process is actually configured with - simulating
    BLINK_ENCRYPTION_KEY having changed since this account was linked."""
    box = SecretBox(get_settings().encryption_key)
    wrong_box = SecretBox(generate_key())
    account = BlinkAccount(
        encrypted_username=box.encrypt("brian@example.com"),
        encrypted_password=box.encrypt("hunter2"),
        encrypted_token_data=wrong_box.encrypt(json.dumps({"refresh_token": "r"})),
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


async def _stale_the_cache(app_session: AsyncSession, camera: Camera) -> None:
    camera.preview_updated_at = datetime.now(UTC) - timedelta(minutes=5)
    await app_session.commit()


async def test_get_camera_preview_falls_back_to_stale_cache_on_auth_failure(
    app_session: AsyncSession, tmp_path: Path
) -> None:
    account, camera = await _make_account_and_camera(app_session)
    storage = get_clip_storage(tmp_path)
    good_path = await get_camera_preview(app_session, get_settings(), camera, storage, force=False)
    await _stale_the_cache(app_session, camera)

    FakeBlinkService.next_error = BlinkAuthError("token expired")
    path = await get_camera_preview(app_session, get_settings(), camera, storage, force=False)

    assert path == good_path
    assert path.read_bytes() == b"preview-bytes"
    await app_session.refresh(account)
    assert account.status == BlinkAccountStatus.ERROR  # still recorded, even though we degraded


async def test_get_camera_preview_falls_back_to_stale_cache_on_generic_error(
    app_session: AsyncSession, tmp_path: Path
) -> None:
    _account, camera = await _make_account_and_camera(app_session)
    storage = get_clip_storage(tmp_path)
    good_path = await get_camera_preview(app_session, get_settings(), camera, storage, force=False)
    await _stale_the_cache(app_session, camera)

    FakeBlinkService.next_error = BlinkError("camera offline")
    path = await get_camera_preview(app_session, get_settings(), camera, storage, force=False)

    assert path == good_path


async def test_get_camera_preview_force_ignores_stale_cache_and_raises(
    app_session: AsyncSession, tmp_path: Path
) -> None:
    """A forced ("Snap now") request is an explicit ask for a live capture -
    it should surface the real failure, not quietly hand back an old frame."""
    _account, camera = await _make_account_and_camera(app_session)
    storage = get_clip_storage(tmp_path)
    await get_camera_preview(app_session, get_settings(), camera, storage, force=False)
    await _stale_the_cache(app_session, camera)

    FakeBlinkService.next_error = BlinkError("camera offline")
    with pytest.raises(BlinkError):
        await get_camera_preview(app_session, get_settings(), camera, storage, force=True)


async def test_get_camera_preview_serves_stale_cache_without_calling_blink_when_disabled(
    app_session: AsyncSession, tmp_path: Path
) -> None:
    """See Settings.disable_blink_network_calls - e2e's seeded account can
    never really talk to Blink, so this should never even try."""
    account, camera = await _make_account_and_camera(app_session)
    storage = get_clip_storage(tmp_path)
    good_path = await get_camera_preview(app_session, get_settings(), camera, storage, force=False)
    await _stale_the_cache(app_session, camera)
    FakeBlinkService.calls = []

    disabled_settings = PlainSettings(disable_blink_network_calls=True)
    path = await get_camera_preview(app_session, disabled_settings, camera, storage, force=False)

    assert path == good_path
    assert FakeBlinkService.calls == []
    await app_session.refresh(account)
    assert account.status == BlinkAccountStatus.ACTIVE


async def test_get_camera_preview_force_also_serves_cache_when_disabled(
    app_session: AsyncSession, tmp_path: Path
) -> None:
    """Even an explicit "Snap now" can't reach a real camera here - disabled
    means disabled regardless of force."""
    _account, camera = await _make_account_and_camera(app_session)
    storage = get_clip_storage(tmp_path)
    good_path = await get_camera_preview(app_session, get_settings(), camera, storage, force=False)
    FakeBlinkService.calls = []

    disabled_settings = PlainSettings(disable_blink_network_calls=True)
    path = await get_camera_preview(app_session, disabled_settings, camera, storage, force=True)

    assert path == good_path
    assert FakeBlinkService.calls == []


async def test_get_camera_preview_raises_when_disabled_with_no_cache(
    app_session: AsyncSession, tmp_path: Path
) -> None:
    _account, camera = await _make_account_and_camera(app_session)
    storage = get_clip_storage(tmp_path)
    disabled_settings = PlainSettings(disable_blink_network_calls=True)

    with pytest.raises(BlinkError, match="disabled"):
        await get_camera_preview(app_session, disabled_settings, camera, storage, force=False)

    assert FakeBlinkService.calls == []


async def test_get_camera_preview_maps_an_undecryptable_token_to_an_auth_error(
    app_session: AsyncSession, tmp_path: Path
) -> None:
    """BLINK_ENCRYPTION_KEY changing since an account was linked (or a bad
    restore) has the same fix as an expired token - re-link - so it should
    surface identically, not as a raw crypto exception."""
    account, camera = await _make_account_with_undecryptable_token(app_session)
    storage = get_clip_storage(tmp_path)

    with pytest.raises(BlinkAuthError):
        await get_camera_preview(app_session, get_settings(), camera, storage, force=False)

    assert FakeBlinkService.calls == []  # never even got as far as constructing a service
    await app_session.refresh(account)
    assert account.status == BlinkAccountStatus.ERROR
    assert account.last_error is not None


async def test_get_camera_preview_does_not_fall_back_to_stale_cache_for_a_decrypt_failure(
    app_session: AsyncSession, tmp_path: Path
) -> None:
    """Unlike a transient BlinkAuthError from the service call itself, a
    decrypt failure means every future request keeps failing the same way
    until re-linked - masking that behind a stale image would hide a
    permanent problem, not a blip."""
    _account, camera = await _make_account_with_undecryptable_token(app_session)
    storage = get_clip_storage(tmp_path)
    stale_path = storage.camera_preview_path(camera.name)
    await storage.write(stale_path, b"stale-bytes")
    camera.preview_path = str(stale_path)
    camera.preview_updated_at = datetime.now(UTC) - timedelta(minutes=5)
    await app_session.commit()

    with pytest.raises(BlinkAuthError):
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


async def test_record_camera_clip_raises_without_touching_the_account_when_disabled(
    app_session: AsyncSession,
) -> None:
    """See Settings.disable_blink_network_calls - still surfaces as a
    failure to the caller (matching live_view.spec.ts's expectation that
    saving a clip against the synthetic e2e account reports an error), but
    never corrupts the shared account row other tests also read."""
    account, camera = await _make_account_and_camera(app_session)
    disabled_settings = PlainSettings(disable_blink_network_calls=True)

    with pytest.raises(BlinkError, match="disabled"):
        await record_camera_clip(app_session, disabled_settings, camera)

    assert FakeBlinkService.calls == []
    await app_session.refresh(account)
    assert account.status == BlinkAccountStatus.ACTIVE
    assert account.last_error is None


async def test_record_camera_clip_maps_an_undecryptable_token_to_an_auth_error(
    app_session: AsyncSession,
) -> None:
    account, camera = await _make_account_with_undecryptable_token(app_session)

    with pytest.raises(BlinkAuthError):
        await record_camera_clip(app_session, get_settings(), camera)

    assert FakeBlinkService.calls == []
    await app_session.refresh(account)
    assert account.status == BlinkAccountStatus.ERROR


# --------------------------------------------------------------- live view


async def test_start_live_view_delegates_to_the_manager(app_session: AsyncSession) -> None:
    _account, camera = await _make_account_and_camera(app_session)
    manager = FakeLiveViewManager()
    handle_sentinel = object()
    FakeBlinkService.next_handle = handle_sentinel

    result = await start_live_view(app_session, get_settings(), camera, manager)

    assert result is manager.next_result
    assert FakeBlinkService.calls == ["live_stream"]
    assert len(manager.calls) == 1
    called_camera_id, called_service, called_handle = manager.calls[0]
    assert called_camera_id == camera.id
    assert called_handle is handle_sentinel
    assert isinstance(called_service, FakeBlinkService)


async def test_start_live_view_marks_account_error_on_auth_failure(
    app_session: AsyncSession,
) -> None:
    account, camera = await _make_account_and_camera(app_session)
    FakeBlinkService.next_error = BlinkAuthError("token expired")
    manager = FakeLiveViewManager()

    with pytest.raises(BlinkAuthError):
        await start_live_view(app_session, get_settings(), camera, manager)

    await app_session.refresh(account)
    assert account.status == BlinkAccountStatus.ERROR
    assert account.last_error == "token expired"
    assert manager.calls == []
    assert FakeBlinkService.instances[-1].closed is True


async def test_start_live_view_closes_the_service_without_touching_the_account_when_unsupported(
    app_session: AsyncSession,
) -> None:
    account, camera = await _make_account_and_camera(app_session)
    FakeBlinkService.next_error = LiveViewUnsupportedError("rtsps:// only")
    manager = FakeLiveViewManager()

    with pytest.raises(LiveViewUnsupportedError):
        await start_live_view(app_session, get_settings(), camera, manager)

    assert manager.calls == []
    assert FakeBlinkService.instances[-1].closed is True
    await app_session.refresh(account)
    assert account.status == BlinkAccountStatus.ACTIVE  # unlike an auth failure, untouched


async def test_start_live_view_propagates_the_managers_own_start_errors(
    app_session: AsyncSession,
) -> None:
    """Once init_live_stream() succeeds, ownership of the service/handle has
    already transferred to the manager (see start_live_view's own docstring)
    - its failures propagate as-is, with no double-close attempted here."""
    _account, camera = await _make_account_and_camera(app_session)
    manager = FakeLiveViewManager()
    manager.next_error = LiveViewStartError("ffmpeg is not installed")

    with pytest.raises(LiveViewStartError):
        await start_live_view(app_session, get_settings(), camera, manager)


async def test_start_live_view_raises_without_calling_blink_when_disabled(
    app_session: AsyncSession,
) -> None:
    _account, camera = await _make_account_and_camera(app_session)
    disabled_settings = PlainSettings(disable_blink_network_calls=True)
    manager = FakeLiveViewManager()

    with pytest.raises(BlinkError, match="disabled"):
        await start_live_view(app_session, disabled_settings, camera, manager)

    assert FakeBlinkService.calls == []
    assert manager.calls == []


async def test_start_live_view_maps_an_undecryptable_token_to_an_auth_error(
    app_session: AsyncSession,
) -> None:
    account, camera = await _make_account_with_undecryptable_token(app_session)
    manager = FakeLiveViewManager()

    with pytest.raises(BlinkAuthError):
        await start_live_view(app_session, get_settings(), camera, manager)

    assert FakeBlinkService.calls == []
    assert manager.calls == []
    await app_session.refresh(account)
    assert account.status == BlinkAccountStatus.ERROR
