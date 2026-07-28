"""LocalClipStorage: atomic writes, safe deletes, real filesystem errors."""

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.storage.service import LocalClipStorage, StorageError, get_clip_storage

RECORDED_AT = datetime(2026, 7, 20, 14, 30, tzinfo=UTC)


@pytest.fixture
def storage(tmp_path: Path) -> LocalClipStorage:
    return LocalClipStorage(tmp_path)


def test_factory_returns_local_storage(tmp_path: Path) -> None:
    assert isinstance(get_clip_storage(tmp_path), LocalClipStorage)


def test_clip_path_and_thumbnail_path_are_namespaced_by_camera_and_date(
    storage: LocalClipStorage,
) -> None:
    camera_id = uuid.uuid4()
    clip_id = uuid.uuid4()
    assert (
        storage.clip_path(camera_id, clip_id, RECORDED_AT)
        == storage.root / str(camera_id) / "2026-07-20" / f"{clip_id}.mp4"
    )
    assert (
        storage.thumbnail_path(camera_id, clip_id, RECORDED_AT)
        == storage.root / str(camera_id) / "2026-07-20" / f"{clip_id}.jpg"
    )


def test_legacy_thumbnail_path_is_the_pre_migration_flat_location(
    storage: LocalClipStorage,
) -> None:
    camera_id = uuid.uuid4()
    clip_id = uuid.uuid4()
    assert (
        storage.legacy_thumbnail_path(camera_id, clip_id)
        == storage.root / str(camera_id) / f"{clip_id}.jpg"
    )


def test_person_and_face_sample_paths_are_namespaced_by_person(
    storage: LocalClipStorage,
) -> None:
    person_id = uuid.uuid4()
    embedding_id = uuid.uuid4()
    assert (
        storage.person_thumbnail_path(person_id)
        == storage.root / "people" / str(person_id) / "profile.jpg"
    )
    assert (
        storage.face_sample_path(person_id, embedding_id)
        == storage.root / "people" / str(person_id) / "samples" / f"{embedding_id}.jpg"
    )


async def test_write_creates_parent_dirs_and_persists_bytes(storage: LocalClipStorage) -> None:
    path = storage.clip_path(uuid.uuid4(), uuid.uuid4(), RECORDED_AT)
    size = await storage.write(path, b"clip-bytes")
    assert size == len(b"clip-bytes")
    assert path.read_bytes() == b"clip-bytes"
    assert not path.with_suffix(path.suffix + ".part").exists()


async def test_write_overwrites_existing_file_atomically(storage: LocalClipStorage) -> None:
    path = storage.clip_path(uuid.uuid4(), uuid.uuid4(), RECORDED_AT)
    await storage.write(path, b"first")
    await storage.write(path, b"second")
    assert path.read_bytes() == b"second"


async def test_write_raises_storage_error_on_permission_denied(
    storage: LocalClipStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    import errno

    def fail_write(*_args: object, **_kwargs: object) -> None:
        # A real PermissionError from the OS carries .errno; constructing one
        # bare (no args) leaves .errno as None, which would silently fall
        # through to the generic branch instead of the one under test.
        raise PermissionError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(Path, "write_bytes", fail_write)
    path = storage.clip_path(uuid.uuid4(), uuid.uuid4(), RECORDED_AT)
    with pytest.raises(StorageError, match="Permission denied"):
        await storage.write(path, b"data")


async def test_write_raises_storage_error_when_disk_full(
    storage: LocalClipStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    import errno

    def fail_write(*_args: object, **_kwargs: object) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(Path, "write_bytes", fail_write)
    path = storage.clip_path(uuid.uuid4(), uuid.uuid4(), RECORDED_AT)
    with pytest.raises(StorageError, match="No space left"):
        await storage.write(path, b"data")


async def test_write_cleans_up_temp_file_on_failure(
    storage: LocalClipStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_replace(self: Path, *_args: object) -> None:
        raise OSError("boom")

    monkeypatch.setattr(Path, "replace", fail_replace)
    path = storage.clip_path(uuid.uuid4(), uuid.uuid4(), RECORDED_AT)
    with pytest.raises(StorageError):
        await storage.write(path, b"data")
    assert not path.with_suffix(path.suffix + ".part").exists()


async def test_delete_removes_existing_file(storage: LocalClipStorage) -> None:
    path = storage.clip_path(uuid.uuid4(), uuid.uuid4(), RECORDED_AT)
    await storage.write(path, b"data")
    await storage.delete(path)
    assert not path.exists()


async def test_delete_is_not_an_error_when_file_is_already_gone(
    storage: LocalClipStorage,
) -> None:
    path = storage.clip_path(uuid.uuid4(), uuid.uuid4(), RECORDED_AT)
    await storage.delete(path)  # never written — must not raise


async def test_delete_raises_storage_error_on_unexpected_os_error(
    storage: LocalClipStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_unlink(*_args: object, **_kwargs: object) -> None:
        raise OSError("locked")

    monkeypatch.setattr(Path, "unlink", fail_unlink)
    path = storage.clip_path(uuid.uuid4(), uuid.uuid4(), RECORDED_AT)
    with pytest.raises(StorageError, match="Failed to delete"):
        await storage.delete(path)
