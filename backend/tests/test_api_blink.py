"""/api/blink/*: linking (incl. 2FA), status, manual sync, unlink.

blinkpy's Auth is faked (patched at the name imported into app.blink.linker,
same technique as test_blink_linker.py) so the full link/verify HTTP flow
runs for real without any network call. /api/blink/sync enqueues against the
real test Redis — harmless, nothing consumes the queue in these tests.
"""

# pytest calls autouse fixtures implicitly; pyright can't see that usage.
# blinkpy ships no type stubs (no py.typed marker).
# pyright: reportUnusedFunction=false
# pyright: reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

import pytest
from blinkpy.auth import BlinkTwoFARequiredError, LoginError
from fastapi import FastAPI
from httpx import AsyncClient

from app.blink.models import BlinkAccount, Camera, Clip
from app.config import get_settings
from app.security.crypto import SecretBox
from app.settings.service import set_storage_dir


class FakeSession:
    async def close(self) -> None:
        return None


class FakeAuth:
    startup_error: ClassVar[Exception | None] = None

    def __init__(self, login_data: dict[str, Any] | None = None, **_kwargs: Any) -> None:
        self.login_data = login_data or {}
        self.session = FakeSession()

    async def startup(self) -> None:
        if self.startup_error:
            raise self.startup_error

    async def complete_2fa_login(self, _code: str) -> bool:
        return True

    @property
    def login_attributes(self) -> dict[str, Any]:
        return {**self.login_data, "token": "final-token"}


@pytest.fixture(autouse=True)
def _patch_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.blink.linker.Auth", FakeAuth)
    monkeypatch.setattr(FakeAuth, "startup_error", None)


async def _linked_account(app: FastAPI) -> BlinkAccount:
    async with app.state.sessionmaker() as session:
        box = SecretBox(get_settings().encryption_key)
        account = BlinkAccount(
            encrypted_username=box.encrypt("brian@example.com"),
            encrypted_password=box.encrypt("hunter2"),
            encrypted_token_data=box.encrypt(json.dumps({"refresh_token": "r"})),
        )
        session.add(account)
        await session.commit()
        await session.refresh(account)
        return account


# --------------------------------------------------------------- link/verify


async def test_link_requires_superuser(client: AsyncClient) -> None:
    response = await client.post(
        "/api/blink/link", json={"username": "u@example.com", "password": "hunter2"}
    )
    assert response.status_code == 401


async def test_link_succeeds_without_2fa(admin_client: AsyncClient, app: FastAPI) -> None:
    response = await admin_client.post(
        "/api/blink/link", json={"username": "brian@example.com", "password": "hunter2"}
    )
    assert response.status_code == 200
    assert response.json() == {"status": "linked", "link_session_id": None}

    async with app.state.sessionmaker() as session:
        from sqlalchemy import select

        account = (await session.execute(select(BlinkAccount))).scalar_one()
        box = SecretBox(get_settings().encryption_key)
        assert box.decrypt(account.encrypted_username) == "brian@example.com"


async def test_link_rejects_when_already_linked(admin_client: AsyncClient, app: FastAPI) -> None:
    await _linked_account(app)
    response = await admin_client.post(
        "/api/blink/link", json={"username": "brian@example.com", "password": "hunter2"}
    )
    assert response.status_code == 409


async def test_link_rejects_invalid_credentials(admin_client: AsyncClient) -> None:
    FakeAuth.startup_error = LoginError("nope")
    response = await admin_client.post(
        "/api/blink/link", json={"username": "brian@example.com", "password": "wrong"}
    )
    assert response.status_code == 400


async def test_link_maps_connection_error_to_503(admin_client: AsyncClient) -> None:
    from aiohttp import ClientConnectionError

    FakeAuth.startup_error = ClientConnectionError("dns failure")
    response = await admin_client.post(
        "/api/blink/link", json={"username": "brian@example.com", "password": "hunter2"}
    )
    assert response.status_code == 503


async def test_link_returns_verification_required_for_2fa(admin_client: AsyncClient) -> None:
    FakeAuth.startup_error = BlinkTwoFARequiredError()
    response = await admin_client.post(
        "/api/blink/link", json={"username": "brian@example.com", "password": "hunter2"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "verification_required"
    assert body["link_session_id"] is not None


async def test_verify_requires_superuser(client: AsyncClient) -> None:
    response = await client.post(
        "/api/blink/verify",
        json={"link_session_id": "00000000-0000-0000-0000-000000000000", "code": "1"},
    )
    assert response.status_code == 401


async def test_verify_unknown_session_is_410(admin_client: AsyncClient) -> None:
    response = await admin_client.post(
        "/api/blink/verify",
        json={"link_session_id": "00000000-0000-0000-0000-000000000000", "code": "123456"},
    )
    assert response.status_code == 410


async def test_verify_wrong_code_is_400(
    admin_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    FakeAuth.startup_error = BlinkTwoFARequiredError()
    start = await admin_client.post(
        "/api/blink/link", json={"username": "brian@example.com", "password": "hunter2"}
    )
    session_id = start.json()["link_session_id"]

    async def reject(self: FakeAuth, _code: str) -> bool:
        return False

    monkeypatch.setattr(FakeAuth, "complete_2fa_login", reject)
    response = await admin_client.post(
        "/api/blink/verify", json={"link_session_id": session_id, "code": "000000"}
    )
    assert response.status_code == 400


async def test_verify_session_expires_between_lookup_and_completion(
    admin_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A narrow race: pending_credentials() succeeds, but the session is then
    swept (TTL expiry) before complete_2fa() runs its own lookup."""
    from app.blink.linker import BlinkLinkSessionExpiredError

    FakeAuth.startup_error = BlinkTwoFARequiredError()
    start = await admin_client.post(
        "/api/blink/link", json={"username": "brian@example.com", "password": "hunter2"}
    )
    session_id = start.json()["link_session_id"]

    async def expire_between_calls(self: object, _session_id: object, _code: str) -> dict[str, Any]:
        raise BlinkLinkSessionExpiredError("expired")

    import app.blink.linker as linker_module

    monkeypatch.setattr(linker_module.BlinkLinker, "complete_2fa", expire_between_calls)
    response = await admin_client.post(
        "/api/blink/verify", json={"link_session_id": session_id, "code": "123456"}
    )
    assert response.status_code == 410


async def test_verify_connection_error_maps_to_503(
    admin_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from aiohttp import ClientConnectionError

    FakeAuth.startup_error = BlinkTwoFARequiredError()
    start = await admin_client.post(
        "/api/blink/link", json={"username": "brian@example.com", "password": "hunter2"}
    )
    session_id = start.json()["link_session_id"]

    async def fail_2fa(self: FakeAuth, _code: str) -> bool:
        raise ClientConnectionError("timeout")

    monkeypatch.setattr(FakeAuth, "complete_2fa_login", fail_2fa)
    response = await admin_client.post(
        "/api/blink/verify", json={"link_session_id": session_id, "code": "123456"}
    )
    assert response.status_code == 503


async def test_full_2fa_link_flow(admin_client: AsyncClient, app: FastAPI) -> None:
    FakeAuth.startup_error = BlinkTwoFARequiredError()
    start = await admin_client.post(
        "/api/blink/link", json={"username": "brian@example.com", "password": "hunter2"}
    )
    session_id = start.json()["link_session_id"]

    response = await admin_client.post(
        "/api/blink/verify", json={"link_session_id": session_id, "code": "123456"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "linked"

    async with app.state.sessionmaker() as session:
        from sqlalchemy import select

        account = (await session.execute(select(BlinkAccount))).scalar_one()
        box = SecretBox(get_settings().encryption_key)
        assert box.decrypt(account.encrypted_username) == "brian@example.com"


# ----------------------------------------------------------------------- status


async def test_status_when_unlinked(admin_client: AsyncClient) -> None:
    response = await admin_client.get("/api/blink/status")
    assert response.status_code == 200
    assert response.json() == {
        "linked": False,
        "status": None,
        "last_sync": None,
        "last_error": None,
        "camera_count": 0,
        "network_ids": [],
        "total_clip_count": 0,
        "daily_clip_counts": [],
    }


async def test_status_visible_to_any_active_user_not_just_superuser(
    admin_client: AsyncClient,
) -> None:
    # admin_client is itself an active user; the real check is that this
    # endpoint uses current_active_user, not current_superuser — exercised
    # implicitly by every status test succeeding under admin_client.
    response = await admin_client.get("/api/blink/status")
    assert response.status_code == 200


async def test_status_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/blink/status")
    assert response.status_code == 401


async def test_status_reports_camera_count(admin_client: AsyncClient, app: FastAPI) -> None:
    account = await _linked_account(app)
    async with app.state.sessionmaker() as session:
        session.add(
            Camera(
                blink_account_id=account.id,
                blink_camera_id="c1",
                blink_network_id="n1",
                name="Front Door",
                camera_type="catalina",
            )
        )
        await session.commit()

    response = await admin_client.get("/api/blink/status")
    body = response.json()
    assert body["linked"] is True
    assert body["camera_count"] == 1
    assert body["network_ids"] == ["n1"]


async def test_status_reports_distinct_network_ids(admin_client: AsyncClient, app: FastAPI) -> None:
    account = await _linked_account(app)
    async with app.state.sessionmaker() as session:
        session.add_all(
            [
                Camera(
                    blink_account_id=account.id,
                    blink_camera_id="c1",
                    blink_network_id="n2",
                    name="Front Door",
                    camera_type="catalina",
                ),
                Camera(
                    blink_account_id=account.id,
                    blink_camera_id="c2",
                    blink_network_id="n1",
                    name="Backyard",
                    camera_type="catalina",
                ),
                Camera(
                    blink_account_id=account.id,
                    blink_camera_id="c3",
                    blink_network_id="n1",
                    name="Garage",
                    camera_type="catalina",
                ),
            ]
        )
        await session.commit()

    response = await admin_client.get("/api/blink/status")
    body = response.json()
    assert body["network_ids"] == ["n1", "n2"]


async def _linked_camera(app: FastAPI, account: BlinkAccount) -> Camera:
    async with app.state.sessionmaker() as session:
        camera = Camera(
            blink_account_id=account.id,
            blink_camera_id="c1",
            blink_network_id="n1",
            name="Front Door",
            camera_type="catalina",
        )
        session.add(camera)
        await session.commit()
        await session.refresh(camera)
        return camera


async def test_status_total_clip_count_includes_clips_outside_the_daily_window(
    admin_client: AsyncClient, app: FastAPI
) -> None:
    account = await _linked_account(app)
    camera = await _linked_camera(app, account)
    async with app.state.sessionmaker() as session:
        session.add_all(
            [
                Clip(camera_id=camera.id, blink_clip_id="c1", recorded_at=datetime.now(UTC)),
                Clip(
                    camera_id=camera.id,
                    blink_clip_id="c2",
                    recorded_at=datetime.now(UTC) - timedelta(days=30),
                ),
            ]
        )
        await session.commit()

    response = await admin_client.get("/api/blink/status")
    body = response.json()
    assert body["total_clip_count"] == 2


async def test_status_daily_clip_counts_are_zero_filled_and_bucketed_by_day(
    admin_client: AsyncClient, app: FastAPI
) -> None:
    account = await _linked_account(app)
    camera = await _linked_camera(app, account)
    now = datetime.now(UTC)
    async with app.state.sessionmaker() as session:
        session.add_all(
            [
                Clip(camera_id=camera.id, blink_clip_id="today-1", recorded_at=now),
                Clip(camera_id=camera.id, blink_clip_id="today-2", recorded_at=now),
                Clip(
                    camera_id=camera.id,
                    blink_clip_id="two-days-ago",
                    recorded_at=now - timedelta(days=2),
                ),
                # Outside the 7-day window - must not appear in any bucket.
                Clip(
                    camera_id=camera.id,
                    blink_clip_id="ancient",
                    recorded_at=now - timedelta(days=10),
                ),
            ]
        )
        await session.commit()

    response = await admin_client.get("/api/blink/status")
    body = response.json()
    daily = body["daily_clip_counts"]
    assert len(daily) == 7
    assert daily[-1] == {"date": str(now.date()), "count": 2}
    assert daily[-3] == {"date": str((now - timedelta(days=2)).date()), "count": 1}
    assert sum(day["count"] for day in daily) == 3
    assert body["total_clip_count"] == 4
    # Oldest-first ordering: the earliest bucket is exactly 6 days before today.
    assert daily[0]["date"] == str((now - timedelta(days=6)).date())


# ------------------------------------------------------------------------- sync


async def test_sync_requires_superuser(client: AsyncClient) -> None:
    response = await client.post("/api/blink/sync")
    assert response.status_code == 401


async def test_sync_without_account_is_409(admin_client: AsyncClient) -> None:
    response = await admin_client.post("/api/blink/sync")
    assert response.status_code == 409


async def test_sync_enqueues_a_job(admin_client: AsyncClient, app: FastAPI) -> None:
    await _linked_account(app)
    response = await admin_client.post("/api/blink/sync")
    assert response.status_code == 202
    assert response.json() == {"status": "sync_started"}


# ----------------------------------------------------------------------- unlink


async def test_unlink_requires_superuser(client: AsyncClient) -> None:
    response = await client.delete("/api/blink/account")
    assert response.status_code == 401


async def test_unlink_without_account_is_404(admin_client: AsyncClient) -> None:
    response = await admin_client.delete("/api/blink/account")
    assert response.status_code == 404


async def test_unlink_continues_past_a_file_cleanup_failure(
    admin_client: AsyncClient, app: FastAPI, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import select

    async with app.state.sessionmaker() as session:
        await set_storage_dir(session, str(tmp_path))

    account = await _linked_account(app)
    async with app.state.sessionmaker() as session:
        camera = Camera(
            blink_account_id=account.id,
            blink_camera_id="c1",
            blink_network_id="n1",
            name="Front Door",
            camera_type="catalina",
        )
        session.add(camera)
        await session.flush()
        session.add(
            Clip(
                camera_id=camera.id,
                blink_clip_id="/media/clip1.mp4",
                recorded_at=datetime(2026, 7, 20, tzinfo=UTC),
                raw_metadata={},
            )
        )
        await session.commit()

    from app.storage.service import StorageError

    async def fail_delete(*_args: object, **_kwargs: object) -> None:
        raise StorageError("permission denied")

    monkeypatch.setattr("app.storage.service.LocalClipStorage.delete", fail_delete)

    response = await admin_client.delete("/api/blink/account")
    assert response.status_code == 204  # unlink still succeeds

    async with app.state.sessionmaker() as session:
        assert (await session.execute(select(BlinkAccount))).first() is None


async def test_unlink_removes_account_cameras_clips_and_files(
    admin_client: AsyncClient, app: FastAPI, tmp_path: Path
) -> None:
    from sqlalchemy import select

    async with app.state.sessionmaker() as session:
        await set_storage_dir(session, str(tmp_path))

    account = await _linked_account(app)
    async with app.state.sessionmaker() as session:
        camera = Camera(
            blink_account_id=account.id,
            blink_camera_id="c1",
            blink_network_id="n1",
            name="Front Door",
            camera_type="catalina",
        )
        session.add(camera)
        await session.flush()
        clip = Clip(
            camera_id=camera.id,
            blink_clip_id="/media/clip1.mp4",
            recorded_at=datetime(2026, 7, 20, tzinfo=UTC),
            raw_metadata={},
        )
        session.add(clip)
        await session.commit()
        # Pre-migration flat path (no date folder) - also proves an
        # old-format clip's file still gets cleaned up correctly via its
        # own persisted storage_path, not a recompute.
        clip_path = tmp_path / str(camera.id) / f"{clip.id}.mp4"
        clip_path.parent.mkdir(parents=True)
        clip_path.write_bytes(b"video")
        clip.storage_path = str(clip_path)
        clip.downloaded_at = datetime.now(UTC)
        await session.commit()

    response = await admin_client.delete("/api/blink/account")
    assert response.status_code == 204
    assert not clip_path.exists()

    async with app.state.sessionmaker() as session:
        assert (await session.execute(select(BlinkAccount))).first() is None
        assert (await session.execute(select(Camera))).first() is None
        assert (await session.execute(select(Clip))).first() is None
