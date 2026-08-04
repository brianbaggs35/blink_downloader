"""Moving a clip's bytes between local disk and a cloud provider, and the
two-tier temporary-link mechanism (real S3 presigned URL vs. our own
self-issued encrypted bearer token for Google Drive/OneDrive).

Cloud providers are faked at the CloudClient boundary (never a real S3/
Google/Microsoft call) - matching test_integrations_cloud.py's convention
for the SDK clients themselves.
"""

# Untyped monkeypatch.setattr(str, lambda) call sites below - same as
# test_integrations_cloud.py.
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownLambdaType=false

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.blink.models import BlinkAccount, Camera, Clip, StorageBackend
from app.config import get_settings
from app.integrations.archive import (
    ArchiveError,
    archive_clip,
    create_temporary_link,
    resolve_temporary_link_token,
    restore_clip,
)
from app.integrations.cloud import CloudStorageError
from app.security.crypto import SecretBox
from app.storage.service import ClipStorage, LocalClipStorage, StorageError, get_clip_storage


async def _make_camera(session: AsyncSession) -> Camera:
    box = SecretBox(get_settings().encryption_key)
    account = BlinkAccount(
        encrypted_username=box.encrypt("a@example.com"),
        encrypted_password=box.encrypt("hunter2"),
        encrypted_token_data=box.encrypt("{}"),
    )
    session.add(account)
    await session.flush()
    camera = Camera(
        blink_account_id=account.id,
        blink_camera_id="cam-1",
        blink_network_id="net-1",
        name="Driveway",
        camera_type="catalina",
    )
    session.add(camera)
    await session.commit()
    await session.refresh(camera)
    return camera


async def _make_downloaded_clip(
    session: AsyncSession, camera: Camera, storage: ClipStorage, content: bytes = b"clip-bytes"
) -> Clip:
    clip = Clip(
        camera_id=camera.id,
        blink_clip_id=f"/media/{uuid.uuid4()}.mp4",
        recorded_at=datetime(2026, 7, 20, tzinfo=UTC),
        raw_metadata={},
    )
    session.add(clip)
    await session.commit()
    await session.refresh(clip)

    path = storage.clip_path(camera.name, clip.id, clip.recorded_at)
    await storage.write(path, content)
    clip.storage_path = str(path)
    clip.filename = path.name
    clip.file_size_bytes = len(content)
    clip.downloaded_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(clip)
    return clip


class _FakeCloudClient:
    def __init__(
        self,
        *,
        upload_result: str = "remote-key-123",
        download_result: bytes = b"remote-bytes",
        raise_on: set[str] | None = None,
    ) -> None:
        self.raise_on = raise_on or set()
        self.upload_result = upload_result
        self.download_result = download_result
        self.uploaded: list[tuple[str, bytes]] = []
        self.downloaded: list[str] = []
        self.deleted: list[str] = []

    async def upload(self, name: str, data: bytes) -> str:
        self.uploaded.append((name, data))
        if "upload" in self.raise_on:
            raise CloudStorageError("upload boom")
        return self.upload_result

    async def download(self, key: str) -> bytes:
        self.downloaded.append(key)
        if "download" in self.raise_on:
            raise CloudStorageError("download boom")
        return self.download_result

    async def delete(self, key: str) -> None:
        self.deleted.append(key)
        if "delete" in self.raise_on:
            raise CloudStorageError("delete boom")

    async def test_connection(self) -> None:
        pass


# ------------------------------------------------------------- archive_clip


async def test_archive_clip_rejects_local_as_a_destination(
    app_session: AsyncSession, tmp_path: Path
) -> None:
    camera = await _make_camera(app_session)
    storage = get_clip_storage(tmp_path)
    clip = await _make_downloaded_clip(app_session, camera, storage)
    with pytest.raises(ArchiveError, match="not an archive destination"):
        await archive_clip(app_session, clip, StorageBackend.LOCAL, "key", storage)


async def test_archive_clip_rejects_an_already_archived_clip(
    app_session: AsyncSession, tmp_path: Path
) -> None:
    camera = await _make_camera(app_session)
    storage = get_clip_storage(tmp_path)
    clip = await _make_downloaded_clip(app_session, camera, storage)
    clip.storage_backend = StorageBackend.S3
    await app_session.commit()
    with pytest.raises(ArchiveError, match="already archived"):
        await archive_clip(app_session, clip, StorageBackend.S3, "key", storage)


async def test_archive_clip_rejects_a_clip_not_yet_downloaded(
    app_session: AsyncSession, tmp_path: Path
) -> None:
    camera = await _make_camera(app_session)
    clip = Clip(
        camera_id=camera.id,
        blink_clip_id="/media/not-downloaded.mp4",
        recorded_at=datetime(2026, 7, 20, tzinfo=UTC),
        raw_metadata={},
    )
    app_session.add(clip)
    await app_session.commit()
    await app_session.refresh(clip)
    storage = get_clip_storage(tmp_path)
    with pytest.raises(ArchiveError, match="not been downloaded"):
        await archive_clip(app_session, clip, StorageBackend.S3, "key", storage)


async def test_archive_clip_rejects_an_unconfigured_backend(
    app_session: AsyncSession, tmp_path: Path
) -> None:
    camera = await _make_camera(app_session)
    storage = get_clip_storage(tmp_path)
    clip = await _make_downloaded_clip(app_session, camera, storage)
    with pytest.raises(ArchiveError, match="not configured"):
        await archive_clip(
            app_session, clip, StorageBackend.S3, get_settings().encryption_key, storage
        )


async def test_archive_clip_uploads_deletes_local_and_updates_the_clip(
    monkeypatch: pytest.MonkeyPatch, app_session: AsyncSession, tmp_path: Path
) -> None:
    camera = await _make_camera(app_session)
    storage = get_clip_storage(tmp_path)
    clip = await _make_downloaded_clip(app_session, camera, storage, content=b"hello-world")
    fake = _FakeCloudClient(upload_result="clips/abc.mp4")
    monkeypatch.setattr("app.integrations.archive.build_s3_client", lambda *_a, **_kw: fake)

    await archive_clip(app_session, clip, StorageBackend.S3, get_settings().encryption_key, storage)

    assert fake.uploaded == [(f"{clip.id}.mp4", b"hello-world")]
    assert clip.storage_backend == StorageBackend.S3
    assert clip.storage_path == "clips/abc.mp4"
    local_path = storage.clip_path(camera.name, clip.id, clip.recorded_at)
    assert not local_path.exists()


async def test_archive_clip_wraps_upload_errors(
    monkeypatch: pytest.MonkeyPatch, app_session: AsyncSession, tmp_path: Path
) -> None:
    camera = await _make_camera(app_session)
    storage = get_clip_storage(tmp_path)
    clip = await _make_downloaded_clip(app_session, camera, storage)
    fake = _FakeCloudClient(raise_on={"upload"})
    monkeypatch.setattr("app.integrations.archive.build_s3_client", lambda *_a, **_kw: fake)

    with pytest.raises(ArchiveError, match="upload boom"):
        await archive_clip(
            app_session, clip, StorageBackend.S3, get_settings().encryption_key, storage
        )
    assert clip.storage_backend == StorageBackend.LOCAL


async def test_archive_clip_raises_when_the_local_file_is_missing(
    monkeypatch: pytest.MonkeyPatch, app_session: AsyncSession, tmp_path: Path
) -> None:
    camera = await _make_camera(app_session)
    storage = get_clip_storage(tmp_path)
    clip = await _make_downloaded_clip(app_session, camera, storage)
    storage.clip_path(camera.name, clip.id, clip.recorded_at).unlink()
    fake = _FakeCloudClient()
    monkeypatch.setattr("app.integrations.archive.build_s3_client", lambda *_a, **_kw: fake)

    with pytest.raises(ArchiveError, match="Could not read the local clip file"):
        await archive_clip(
            app_session, clip, StorageBackend.S3, get_settings().encryption_key, storage
        )


async def test_archive_clip_succeeds_despite_a_local_cleanup_failure(
    monkeypatch: pytest.MonkeyPatch, app_session: AsyncSession, tmp_path: Path
) -> None:
    camera = await _make_camera(app_session)
    storage = LocalClipStorage(tmp_path)
    clip = await _make_downloaded_clip(app_session, camera, storage)
    fake = _FakeCloudClient()
    monkeypatch.setattr("app.integrations.archive.build_s3_client", lambda *_a, **_kw: fake)

    async def _raise(_path: Path) -> None:
        raise StorageError("disk gremlins")

    monkeypatch.setattr(storage, "delete", _raise)

    await archive_clip(app_session, clip, StorageBackend.S3, get_settings().encryption_key, storage)
    assert clip.storage_backend == StorageBackend.S3


# ------------------------------------------------------------- restore_clip


async def test_restore_clip_rejects_an_already_local_clip(
    app_session: AsyncSession, tmp_path: Path
) -> None:
    camera = await _make_camera(app_session)
    storage = get_clip_storage(tmp_path)
    clip = await _make_downloaded_clip(app_session, camera, storage)
    with pytest.raises(ArchiveError, match="already local"):
        await restore_clip(app_session, clip, "key", storage)


async def test_restore_clip_rejects_a_clip_with_no_archived_copy(
    app_session: AsyncSession, tmp_path: Path
) -> None:
    camera = await _make_camera(app_session)
    clip = Clip(
        camera_id=camera.id,
        blink_clip_id="/media/x.mp4",
        recorded_at=datetime(2026, 7, 20, tzinfo=UTC),
        raw_metadata={},
        storage_backend=StorageBackend.S3,
    )
    app_session.add(clip)
    await app_session.commit()
    storage = get_clip_storage(tmp_path)
    with pytest.raises(ArchiveError, match="no archived copy"):
        await restore_clip(app_session, clip, "key", storage)


async def test_restore_clip_rejects_an_unconfigured_backend(
    app_session: AsyncSession, tmp_path: Path
) -> None:
    camera = await _make_camera(app_session)
    clip = Clip(
        camera_id=camera.id,
        blink_clip_id="/media/x.mp4",
        recorded_at=datetime(2026, 7, 20, tzinfo=UTC),
        raw_metadata={},
        storage_backend=StorageBackend.S3,
        storage_path="clips/x.mp4",
    )
    app_session.add(clip)
    await app_session.commit()
    storage = get_clip_storage(tmp_path)
    with pytest.raises(ArchiveError, match="not configured"):
        await restore_clip(app_session, clip, get_settings().encryption_key, storage)


async def test_restore_clip_downloads_deletes_remote_and_updates_the_clip(
    monkeypatch: pytest.MonkeyPatch, app_session: AsyncSession, tmp_path: Path
) -> None:
    camera = await _make_camera(app_session)
    clip = Clip(
        camera_id=camera.id,
        blink_clip_id="/media/x.mp4",
        recorded_at=datetime(2026, 7, 20, tzinfo=UTC),
        raw_metadata={},
        storage_backend=StorageBackend.S3,
        storage_path="clips/x.mp4",
    )
    app_session.add(clip)
    await app_session.commit()
    await app_session.refresh(clip)
    storage = get_clip_storage(tmp_path)
    fake = _FakeCloudClient(download_result=b"restored-bytes")
    monkeypatch.setattr("app.integrations.archive.build_s3_client", lambda *_a, **_kw: fake)

    await restore_clip(app_session, clip, get_settings().encryption_key, storage)

    assert fake.downloaded == ["clips/x.mp4"]
    assert fake.deleted == ["clips/x.mp4"]
    assert clip.storage_backend == StorageBackend.LOCAL
    local_path = Path(clip.storage_path)  # type: ignore[arg-type]
    assert local_path.read_bytes() == b"restored-bytes"


async def test_restore_clip_wraps_download_errors(
    monkeypatch: pytest.MonkeyPatch, app_session: AsyncSession, tmp_path: Path
) -> None:
    camera = await _make_camera(app_session)
    clip = Clip(
        camera_id=camera.id,
        blink_clip_id="/media/x.mp4",
        recorded_at=datetime(2026, 7, 20, tzinfo=UTC),
        raw_metadata={},
        storage_backend=StorageBackend.S3,
        storage_path="clips/x.mp4",
    )
    app_session.add(clip)
    await app_session.commit()
    storage = get_clip_storage(tmp_path)
    fake = _FakeCloudClient(raise_on={"download"})
    monkeypatch.setattr("app.integrations.archive.build_s3_client", lambda *_a, **_kw: fake)

    with pytest.raises(ArchiveError, match="download boom"):
        await restore_clip(app_session, clip, get_settings().encryption_key, storage)


async def test_restore_clip_succeeds_despite_a_remote_cleanup_failure(
    monkeypatch: pytest.MonkeyPatch, app_session: AsyncSession, tmp_path: Path
) -> None:
    camera = await _make_camera(app_session)
    clip = Clip(
        camera_id=camera.id,
        blink_clip_id="/media/x.mp4",
        recorded_at=datetime(2026, 7, 20, tzinfo=UTC),
        raw_metadata={},
        storage_backend=StorageBackend.S3,
        storage_path="clips/x.mp4",
    )
    app_session.add(clip)
    await app_session.commit()
    storage = get_clip_storage(tmp_path)
    fake = _FakeCloudClient(raise_on={"delete"})
    monkeypatch.setattr("app.integrations.archive.build_s3_client", lambda *_a, **_kw: fake)

    await restore_clip(app_session, clip, get_settings().encryption_key, storage)
    assert clip.storage_backend == StorageBackend.LOCAL


async def test_restore_clip_wraps_local_write_errors(
    monkeypatch: pytest.MonkeyPatch, app_session: AsyncSession, tmp_path: Path
) -> None:
    camera = await _make_camera(app_session)
    clip = Clip(
        camera_id=camera.id,
        blink_clip_id="/media/x.mp4",
        recorded_at=datetime(2026, 7, 20, tzinfo=UTC),
        raw_metadata={},
        storage_backend=StorageBackend.S3,
        storage_path="clips/x.mp4",
    )
    app_session.add(clip)
    await app_session.commit()
    storage = LocalClipStorage(tmp_path)
    fake = _FakeCloudClient()
    monkeypatch.setattr("app.integrations.archive.build_s3_client", lambda *_a, **_kw: fake)

    async def _raise(_path: Path, _data: bytes) -> int:
        raise StorageError("no space left")

    monkeypatch.setattr(storage, "write", _raise)

    with pytest.raises(ArchiveError, match="Could not write the restored clip locally"):
        await restore_clip(app_session, clip, get_settings().encryption_key, storage)


async def test_restore_clip_from_google_drive_dispatches_to_the_right_client(
    monkeypatch: pytest.MonkeyPatch, app_session: AsyncSession, tmp_path: Path
) -> None:
    camera = await _make_camera(app_session)
    clip = Clip(
        camera_id=camera.id,
        blink_clip_id="/media/x.mp4",
        recorded_at=datetime(2026, 7, 20, tzinfo=UTC),
        raw_metadata={},
        storage_backend=StorageBackend.GOOGLE_DRIVE,
        storage_path="file-123",
    )
    app_session.add(clip)
    await app_session.commit()
    storage = get_clip_storage(tmp_path)
    fake = _FakeCloudClient(download_result=b"drive-bytes")
    monkeypatch.setattr(
        "app.integrations.archive.build_google_drive_client", lambda *_a, **_kw: fake
    )

    await restore_clip(app_session, clip, get_settings().encryption_key, storage)

    assert fake.downloaded == ["file-123"]
    assert clip.storage_backend == StorageBackend.LOCAL


async def test_restore_clip_from_onedrive_dispatches_to_the_right_client(
    monkeypatch: pytest.MonkeyPatch, app_session: AsyncSession, tmp_path: Path
) -> None:
    camera = await _make_camera(app_session)
    clip = Clip(
        camera_id=camera.id,
        blink_clip_id="/media/x.mp4",
        recorded_at=datetime(2026, 7, 20, tzinfo=UTC),
        raw_metadata={},
        storage_backend=StorageBackend.ONEDRIVE,
        storage_path="item-456",
    )
    app_session.add(clip)
    await app_session.commit()
    storage = get_clip_storage(tmp_path)
    fake = _FakeCloudClient(download_result=b"onedrive-bytes")
    monkeypatch.setattr("app.integrations.archive.build_onedrive_client", lambda *_a, **_kw: fake)

    await restore_clip(app_session, clip, get_settings().encryption_key, storage)

    assert fake.downloaded == ["item-456"]
    assert clip.storage_backend == StorageBackend.LOCAL


# ------------------------------------------------------ create_temporary_link


async def test_create_temporary_link_rejects_a_local_clip(
    app_session: AsyncSession, tmp_path: Path
) -> None:
    camera = await _make_camera(app_session)
    storage = get_clip_storage(tmp_path)
    clip = await _make_downloaded_clip(app_session, camera, storage)
    with pytest.raises(ArchiveError, match="stored locally"):
        await create_temporary_link(
            app_session, clip, "key", download_base_url="https://app.example/api/storage/download/"
        )


async def test_create_temporary_link_rejects_a_clip_with_no_archived_copy(
    app_session: AsyncSession,
) -> None:
    camera = await _make_camera(app_session)
    clip = Clip(
        camera_id=camera.id,
        blink_clip_id="/media/x.mp4",
        recorded_at=datetime(2026, 7, 20, tzinfo=UTC),
        raw_metadata={},
        storage_backend=StorageBackend.S3,
    )
    app_session.add(clip)
    await app_session.commit()
    with pytest.raises(ArchiveError, match="no archived copy"):
        await create_temporary_link(
            app_session, clip, "key", download_base_url="https://app.example/api/storage/download/"
        )


async def test_create_temporary_link_s3_returns_a_real_presigned_url(
    monkeypatch: pytest.MonkeyPatch, app_session: AsyncSession
) -> None:
    camera = await _make_camera(app_session)
    clip = Clip(
        camera_id=camera.id,
        blink_clip_id="/media/x.mp4",
        recorded_at=datetime(2026, 7, 20, tzinfo=UTC),
        raw_metadata={},
        storage_backend=StorageBackend.S3,
        storage_path="clips/x.mp4",
    )
    app_session.add(clip)
    await app_session.commit()

    class _FakeS3:
        async def presigned_url(self, key: str, expires_in: int) -> str:
            assert key == "clips/x.mp4"
            return "https://s3.example/clips/x.mp4?X-Amz-Signature=abc"

    monkeypatch.setattr("app.integrations.archive.build_s3_client", lambda *_a, **_kw: _FakeS3())
    result = await create_temporary_link(
        app_session,
        clip,
        get_settings().encryption_key,
        download_base_url="https://app.example/api/storage/download/",
    )
    assert result.url == "https://s3.example/clips/x.mp4?X-Amz-Signature=abc"
    assert result.expires_at > datetime.now(UTC)


async def test_create_temporary_link_s3_not_configured(app_session: AsyncSession) -> None:
    camera = await _make_camera(app_session)
    clip = Clip(
        camera_id=camera.id,
        blink_clip_id="/media/x.mp4",
        recorded_at=datetime(2026, 7, 20, tzinfo=UTC),
        raw_metadata={},
        storage_backend=StorageBackend.S3,
        storage_path="clips/x.mp4",
    )
    app_session.add(clip)
    await app_session.commit()
    with pytest.raises(ArchiveError, match="S3 is not configured"):
        await create_temporary_link(
            app_session,
            clip,
            get_settings().encryption_key,
            download_base_url="https://app.example/api/storage/download/",
        )


async def test_create_temporary_link_s3_wraps_errors(
    monkeypatch: pytest.MonkeyPatch, app_session: AsyncSession
) -> None:
    camera = await _make_camera(app_session)
    clip = Clip(
        camera_id=camera.id,
        blink_clip_id="/media/x.mp4",
        recorded_at=datetime(2026, 7, 20, tzinfo=UTC),
        raw_metadata={},
        storage_backend=StorageBackend.S3,
        storage_path="clips/x.mp4",
    )
    app_session.add(clip)
    await app_session.commit()

    class _RaisingS3:
        async def presigned_url(self, key: str, expires_in: int) -> str:
            raise CloudStorageError("no signature for you")

    monkeypatch.setattr("app.integrations.archive.build_s3_client", lambda *_a, **_kw: _RaisingS3())
    with pytest.raises(ArchiveError, match="no signature for you"):
        await create_temporary_link(
            app_session,
            clip,
            get_settings().encryption_key,
            download_base_url="https://app.example/api/storage/download/",
        )


async def test_create_temporary_link_google_drive_is_a_path_style_bearer_token(
    app_session: AsyncSession,
) -> None:
    """The bug this guards against: a token in the query string
    (?token=...) would never reach GET /download/{token}, which declares
    token as a path parameter - the URL must be download_base_url + token,
    not download_base_url + "?token=" + token."""
    camera = await _make_camera(app_session)
    clip = Clip(
        camera_id=camera.id,
        blink_clip_id="/media/x.mp4",
        recorded_at=datetime(2026, 7, 20, tzinfo=UTC),
        raw_metadata={},
        storage_backend=StorageBackend.GOOGLE_DRIVE,
        storage_path="file-123",
    )
    app_session.add(clip)
    await app_session.commit()
    await app_session.refresh(clip)

    base_url = "https://app.example/api/storage/download/"
    result = await create_temporary_link(
        app_session, clip, get_settings().encryption_key, download_base_url=base_url
    )

    assert result.url.startswith(base_url)
    token = result.url.removeprefix(base_url)
    assert "?" not in token
    assert "token=" not in token

    resolved_clip_id, resolved_backend = resolve_temporary_link_token(
        token, get_settings().encryption_key
    )
    assert resolved_clip_id == clip.id
    assert resolved_backend == StorageBackend.GOOGLE_DRIVE


async def test_create_temporary_link_onedrive_also_uses_a_bearer_token(
    app_session: AsyncSession,
) -> None:
    camera = await _make_camera(app_session)
    clip = Clip(
        camera_id=camera.id,
        blink_clip_id="/media/x.mp4",
        recorded_at=datetime(2026, 7, 20, tzinfo=UTC),
        raw_metadata={},
        storage_backend=StorageBackend.ONEDRIVE,
        storage_path="item-456",
    )
    app_session.add(clip)
    await app_session.commit()

    base_url = "https://app.example/api/storage/download/"
    result = await create_temporary_link(
        app_session, clip, get_settings().encryption_key, download_base_url=base_url
    )
    token = result.url.removeprefix(base_url)
    resolved_clip_id, resolved_backend = resolve_temporary_link_token(
        token, get_settings().encryption_key
    )
    assert resolved_clip_id == clip.id
    assert resolved_backend == StorageBackend.ONEDRIVE


# ------------------------------------------------- resolve_temporary_link_token


def test_resolve_temporary_link_token_rejects_garbage() -> None:
    with pytest.raises(ArchiveError, match="invalid"):
        resolve_temporary_link_token("not-a-real-token", get_settings().encryption_key)


def test_resolve_temporary_link_token_rejects_an_expired_token() -> None:
    payload = {
        "clip_id": str(uuid.uuid4()),
        "backend": "s3",
        "expires_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
    }
    token = SecretBox(get_settings().encryption_key).encrypt(json.dumps(payload))
    with pytest.raises(ArchiveError, match="expired"):
        resolve_temporary_link_token(token, get_settings().encryption_key)
