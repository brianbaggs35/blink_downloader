"""/api/storage/*: usage summary (any signed-in user), archive/restore
(admin, enqueues arq jobs against the real test Redis - harmless, nothing
consumes the queue here, same convention as test_api_clips.py's bulk
actions), temporary links, and the token-gated download proxy.

Cloud providers are faked at whichever module actually calls build_*_client
(app.api.storage for the download proxy, app.integrations.archive for the
link-creation path it owns) - never a real S3/Google/Microsoft call.
"""

# Untyped monkeypatch.setattr(str, lambda) call sites below - same as
# test_integrations_cloud.py.
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownLambdaType=false

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.blink.models import BlinkAccount, Camera, Clip, StorageBackend
from app.config import get_settings
from app.integrations.archive import create_temporary_link
from app.integrations.cloud import CloudStorageError
from app.security.crypto import SecretBox


async def _make_camera(app: FastAPI, name: str = "Front Door") -> Camera:
    async with app.state.sessionmaker() as session:
        box = SecretBox(get_settings().encryption_key)
        account = BlinkAccount(
            encrypted_username=box.encrypt("u"),
            encrypted_password=box.encrypt("p"),
            encrypted_token_data=box.encrypt("{}"),
        )
        session.add(account)
        await session.flush()
        camera = Camera(
            blink_account_id=account.id,
            blink_camera_id=f"cam-{name}",
            blink_network_id="net-1",
            name=name,
            camera_type="catalina",
        )
        session.add(camera)
        await session.commit()
        await session.refresh(camera)
        return camera


async def _make_clip(
    app: FastAPI,
    camera: Camera,
    *,
    downloaded: bool = False,
    backend: StorageBackend = StorageBackend.LOCAL,
    storage_path: str | None = None,
    tmp_path: Path | None = None,
    content: bytes = b"fake-video-bytes",
) -> Clip:
    async with app.state.sessionmaker() as session:
        clip = Clip(
            camera_id=camera.id,
            blink_clip_id=f"/media/{uuid.uuid4()}.mp4",
            recorded_at=datetime(2026, 7, 20, tzinfo=UTC),
            raw_metadata={},
            storage_backend=backend,
        )
        session.add(clip)
        await session.commit()
        await session.refresh(clip)

        if downloaded:
            if backend == StorageBackend.LOCAL:
                assert tmp_path is not None
                path = tmp_path / str(camera.id) / f"{clip.id}.mp4"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                clip.storage_path = str(path)
            else:
                clip.storage_path = storage_path or f"remote/{clip.id}.mp4"
            clip.filename = f"{clip.id}.mp4"
            clip.file_size_bytes = len(content)
            clip.downloaded_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(clip)
        return clip


# ------------------------------------------------------------------- summary


async def test_summary_requires_authentication(client: AsyncClient) -> None:
    assert (await client.get("/api/storage/summary")).status_code == 401


async def test_summary_is_open_to_a_non_admin_viewer(viewer_client: AsyncClient) -> None:
    assert (await viewer_client.get("/api/storage/summary")).status_code == 200


async def test_summary_groups_by_backend(
    admin_client: AsyncClient, app: FastAPI, tmp_path: Path
) -> None:
    camera = await _make_camera(app)
    await _make_clip(app, camera, downloaded=True, tmp_path=tmp_path, content=b"a" * 10)
    await _make_clip(app, camera, downloaded=True, tmp_path=tmp_path, content=b"b" * 20)
    await _make_clip(
        app,
        camera,
        downloaded=True,
        backend=StorageBackend.S3,
        storage_path="clips/x.mp4",
        content=b"c" * 30,
    )
    await _make_clip(app, camera, downloaded=False)  # not downloaded, excluded

    response = await admin_client.get("/api/storage/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["total_clips"] == 3
    assert body["total_bytes"] == 60
    by_backend = {row["backend"]: row for row in body["by_backend"]}
    assert by_backend["local"]["clip_count"] == 2
    assert by_backend["local"]["total_bytes"] == 30
    assert by_backend["s3"]["clip_count"] == 1
    assert by_backend["s3"]["total_bytes"] == 30
    assert body["local_quota_bytes"] is None


async def test_summary_reports_the_configured_local_quota(admin_client: AsyncClient) -> None:
    quota = 500 * 1024**3
    await admin_client.patch("/api/settings/storage", json={"local_storage_quota_bytes": quota})
    response = await admin_client.get("/api/storage/summary")
    assert response.json()["local_quota_bytes"] == quota


async def test_summary_connected_backends_always_includes_local(
    admin_client: AsyncClient,
) -> None:
    response = await admin_client.get("/api/storage/summary")
    assert response.json()["connected_backends"] == ["local"]


async def test_summary_connected_backends_includes_a_configured_cloud_backend(
    monkeypatch: pytest.MonkeyPatch, admin_client: AsyncClient
) -> None:
    class _FakeS3:
        async def test_connection(self) -> None:
            pass

    monkeypatch.setattr("app.api.storage.build_s3_client", lambda *_a, **_kw: _FakeS3())
    response = await admin_client.get("/api/storage/summary")
    assert set(response.json()["connected_backends"]) == {"local", "s3"}


async def test_summary_connected_backends_is_accurate_for_a_non_admin_viewer(
    monkeypatch: pytest.MonkeyPatch, viewer_client: AsyncClient
) -> None:
    """The credential-bearing /settings/storage-integrations endpoint is
    admin-only, but a viewer must still be able to tell a connected backend
    apart from a merely-hypothetical one - this endpoint is their only
    source for that."""

    class _FakeDrive:
        async def test_connection(self) -> None:
            pass

    monkeypatch.setattr(
        "app.api.storage.build_google_drive_client", lambda *_a, **_kw: _FakeDrive()
    )
    response = await viewer_client.get("/api/storage/summary")
    assert set(response.json()["connected_backends"]) == {"local", "google_drive"}


# ------------------------------------------------------------------- archive


async def test_archive_requires_admin(viewer_client: AsyncClient) -> None:
    response = await viewer_client.post(
        "/api/storage/archive", json={"clip_ids": [str(uuid.uuid4())], "backend": "s3"}
    )
    assert response.status_code == 403


async def test_archive_rejects_an_unconfigured_backend(
    admin_client: AsyncClient, app: FastAPI
) -> None:
    camera = await _make_camera(app)
    clip = await _make_clip(app, camera)
    response = await admin_client.post(
        "/api/storage/archive", json={"clip_ids": [str(clip.id)], "backend": "s3"}
    )
    assert response.status_code == 400


async def test_archive_enqueues_eligible_clips_and_counts_the_rest_as_failed(
    monkeypatch: pytest.MonkeyPatch, admin_client: AsyncClient, app: FastAPI, tmp_path: Path
) -> None:
    class _FakeS3:
        async def test_connection(self) -> None:
            pass

    monkeypatch.setattr("app.api.storage.build_s3_client", lambda *_a, **_kw: _FakeS3())
    camera = await _make_camera(app)
    eligible = await _make_clip(app, camera, downloaded=True, tmp_path=tmp_path)
    already_archived = await _make_clip(
        app, camera, downloaded=True, backend=StorageBackend.S3, storage_path="clips/y.mp4"
    )
    missing_id = uuid.uuid4()

    response = await admin_client.post(
        "/api/storage/archive",
        json={
            "clip_ids": [str(eligible.id), str(already_archived.id), str(missing_id)],
            "backend": "s3",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"succeeded": 1, "failed": 2}


async def test_archive_to_google_drive_when_configured(
    monkeypatch: pytest.MonkeyPatch, admin_client: AsyncClient, app: FastAPI, tmp_path: Path
) -> None:
    class _FakeDrive:
        async def test_connection(self) -> None:
            pass

    monkeypatch.setattr(
        "app.api.storage.build_google_drive_client", lambda *_a, **_kw: _FakeDrive()
    )
    camera = await _make_camera(app)
    clip = await _make_clip(app, camera, downloaded=True, tmp_path=tmp_path)

    response = await admin_client.post(
        "/api/storage/archive", json={"clip_ids": [str(clip.id)], "backend": "google_drive"}
    )
    assert response.status_code == 200
    assert response.json() == {"succeeded": 1, "failed": 0}


async def test_archive_to_onedrive_when_configured(
    monkeypatch: pytest.MonkeyPatch, admin_client: AsyncClient, app: FastAPI, tmp_path: Path
) -> None:
    class _FakeOneDrive:
        async def test_connection(self) -> None:
            pass

    monkeypatch.setattr("app.api.storage.build_onedrive_client", lambda *_a, **_kw: _FakeOneDrive())
    camera = await _make_camera(app)
    clip = await _make_clip(app, camera, downloaded=True, tmp_path=tmp_path)

    response = await admin_client.post(
        "/api/storage/archive", json={"clip_ids": [str(clip.id)], "backend": "onedrive"}
    )
    assert response.status_code == 200
    assert response.json() == {"succeeded": 1, "failed": 0}


# ------------------------------------------------------------------- restore


async def test_restore_requires_admin(viewer_client: AsyncClient) -> None:
    response = await viewer_client.post(
        "/api/storage/restore", json={"clip_ids": [str(uuid.uuid4())]}
    )
    assert response.status_code == 403


async def test_restore_enqueues_archived_clips_and_counts_the_rest_as_failed(
    admin_client: AsyncClient, app: FastAPI, tmp_path: Path
) -> None:
    camera = await _make_camera(app)
    archived = await _make_clip(
        app, camera, downloaded=True, backend=StorageBackend.S3, storage_path="clips/y.mp4"
    )
    already_local = await _make_clip(app, camera, downloaded=True, tmp_path=tmp_path)

    response = await admin_client.post(
        "/api/storage/restore", json={"clip_ids": [str(archived.id), str(already_local.id)]}
    )
    assert response.status_code == 200
    assert response.json() == {"succeeded": 1, "failed": 1}


# --------------------------------------------------------------------- link


async def test_get_link_requires_authentication(client: AsyncClient) -> None:
    response = await client.post(f"/api/storage/clips/{uuid.uuid4()}/link")
    assert response.status_code == 401


async def test_get_link_404s_for_a_missing_clip(admin_client: AsyncClient) -> None:
    response = await admin_client.post(f"/api/storage/clips/{uuid.uuid4()}/link")
    assert response.status_code == 404


async def test_get_link_rejects_a_local_clip(
    admin_client: AsyncClient, app: FastAPI, tmp_path: Path
) -> None:
    camera = await _make_camera(app)
    clip = await _make_clip(app, camera, downloaded=True, tmp_path=tmp_path)
    response = await admin_client.post(f"/api/storage/clips/{clip.id}/link")
    assert response.status_code == 400


async def test_get_link_returns_a_presigned_s3_url(
    monkeypatch: pytest.MonkeyPatch, admin_client: AsyncClient, app: FastAPI
) -> None:
    camera = await _make_camera(app)
    clip = await _make_clip(
        app,
        camera,
        downloaded=True,
        backend=StorageBackend.S3,
        storage_path="clips/x.mp4",
    )

    class _FakeS3:
        async def presigned_url(self, key: str, expires_in: int) -> str:
            return f"https://s3.example/{key}?signed=1"

    monkeypatch.setattr("app.integrations.archive.build_s3_client", lambda *_a, **_kw: _FakeS3())
    response = await admin_client.post(f"/api/storage/clips/{clip.id}/link")
    assert response.status_code == 200
    body = response.json()
    assert body["url"] == "https://s3.example/clips/x.mp4?signed=1"
    assert "expires_at" in body


# ----------------------------------------------------------------- download


async def test_download_rejects_an_invalid_token(admin_client: AsyncClient) -> None:
    response = await admin_client.get("/api/storage/download/not-a-real-token")
    assert response.status_code == 400


async def test_download_404s_when_the_clip_no_longer_matches_the_token(
    monkeypatch: pytest.MonkeyPatch, admin_client: AsyncClient, app: FastAPI
) -> None:
    camera = await _make_camera(app)
    clip = await _make_clip(
        app, camera, downloaded=True, backend=StorageBackend.GOOGLE_DRIVE, storage_path="file-1"
    )
    async with app.state.sessionmaker() as session:
        db_clip = await session.get(Clip, clip.id)
        assert db_clip is not None
        link = await create_temporary_link(
            session,
            db_clip,
            get_settings().encryption_key,
            download_base_url="https://testserver/api/storage/download/",
        )
        # The clip gets restored to local before the link is ever used.
        db_clip.storage_backend = StorageBackend.LOCAL
        await session.commit()

    token = link.url.removeprefix("https://testserver/api/storage/download/")
    response = await admin_client.get(f"/api/storage/download/{token}")
    assert response.status_code == 404


async def test_download_proxies_bytes_from_google_drive(
    monkeypatch: pytest.MonkeyPatch, admin_client: AsyncClient, app: FastAPI
) -> None:
    camera = await _make_camera(app)
    clip = await _make_clip(
        app, camera, downloaded=True, backend=StorageBackend.GOOGLE_DRIVE, storage_path="file-1"
    )
    async with app.state.sessionmaker() as session:
        db_clip = await session.get(Clip, clip.id)
        assert db_clip is not None
        link = await create_temporary_link(
            session,
            db_clip,
            get_settings().encryption_key,
            download_base_url="https://testserver/api/storage/download/",
        )
    token = link.url.removeprefix("https://testserver/api/storage/download/")

    class _FakeDrive:
        async def download(self, file_id: str) -> bytes:
            assert file_id == "file-1"
            return b"drive-clip-bytes"

    monkeypatch.setattr(
        "app.api.storage.build_google_drive_client", lambda *_a, **_kw: _FakeDrive()
    )
    response = await admin_client.get(f"/api/storage/download/{token}")
    assert response.status_code == 200
    assert response.content == b"drive-clip-bytes"
    assert "attachment" in response.headers["content-disposition"]


async def test_download_400s_when_the_provider_is_no_longer_configured(
    monkeypatch: pytest.MonkeyPatch, admin_client: AsyncClient, app: FastAPI
) -> None:
    camera = await _make_camera(app)
    clip = await _make_clip(
        app, camera, downloaded=True, backend=StorageBackend.ONEDRIVE, storage_path="item-1"
    )
    async with app.state.sessionmaker() as session:
        db_clip = await session.get(Clip, clip.id)
        assert db_clip is not None
        link = await create_temporary_link(
            session,
            db_clip,
            get_settings().encryption_key,
            download_base_url="https://testserver/api/storage/download/",
        )
    token = link.url.removeprefix("https://testserver/api/storage/download/")

    monkeypatch.setattr("app.api.storage.build_onedrive_client", lambda *_a, **_kw: None)
    response = await admin_client.get(f"/api/storage/download/{token}")
    assert response.status_code == 400


async def test_download_502s_when_the_provider_download_fails(
    monkeypatch: pytest.MonkeyPatch, admin_client: AsyncClient, app: FastAPI
) -> None:
    camera = await _make_camera(app)
    clip = await _make_clip(
        app, camera, downloaded=True, backend=StorageBackend.ONEDRIVE, storage_path="item-1"
    )
    async with app.state.sessionmaker() as session:
        db_clip = await session.get(Clip, clip.id)
        assert db_clip is not None
        link = await create_temporary_link(
            session,
            db_clip,
            get_settings().encryption_key,
            download_base_url="https://testserver/api/storage/download/",
        )
    token = link.url.removeprefix("https://testserver/api/storage/download/")

    class _RaisingOneDrive:
        async def download(self, item_id: str) -> bytes:
            raise CloudStorageError("Graph is down")

    monkeypatch.setattr(
        "app.api.storage.build_onedrive_client", lambda *_a, **_kw: _RaisingOneDrive()
    )
    response = await admin_client.get(f"/api/storage/download/{token}")
    assert response.status_code == 502
