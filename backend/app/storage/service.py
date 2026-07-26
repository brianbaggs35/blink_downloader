"""Local-disk clip storage: atomic writes, safe deletes, no partial files."""

import asyncio
import errno
import uuid
from pathlib import Path
from typing import Protocol

from app.logs import get_logger

logger = get_logger(__name__)


class StorageError(Exception):
    """Writing, reading, or deleting clip bytes failed."""


class ClipStorage(Protocol):
    def clip_path(self, camera_id: uuid.UUID, clip_id: uuid.UUID) -> Path: ...

    def thumbnail_path(self, camera_id: uuid.UUID, clip_id: uuid.UUID) -> Path: ...

    def vehicle_reference_path(self, camera_id: uuid.UUID) -> Path: ...

    def camera_preview_path(self, camera_id: uuid.UUID) -> Path: ...

    def person_thumbnail_path(self, person_id: uuid.UUID) -> Path: ...

    def face_sample_path(self, person_id: uuid.UUID, face_embedding_id: uuid.UUID) -> Path: ...

    async def write(self, path: Path, data: bytes) -> int:
        """Write ``data`` to ``path`` atomically. Returns the byte count."""
        ...

    async def delete(self, path: Path) -> None:
        """Remove ``path``. Not an error if it's already gone."""
        ...


class LocalClipStorage:
    def __init__(self, root: Path) -> None:
        self.root = root

    def clip_path(self, camera_id: uuid.UUID, clip_id: uuid.UUID) -> Path:
        # Our own UUIDs, never externally-controlled strings, are the only
        # thing that reaches the filesystem — no path-sanitization needed.
        return self.root / str(camera_id) / f"{clip_id}.mp4"

    def thumbnail_path(self, camera_id: uuid.UUID, clip_id: uuid.UUID) -> Path:
        return self.root / str(camera_id) / f"{clip_id}.jpg"

    def vehicle_reference_path(self, camera_id: uuid.UUID) -> Path:
        return self.root / str(camera_id) / "vehicle-reference.jpg"

    def camera_preview_path(self, camera_id: uuid.UUID) -> Path:
        return self.root / str(camera_id) / "preview.jpg"

    def person_thumbnail_path(self, person_id: uuid.UUID) -> Path:
        return self.root / "people" / str(person_id) / "profile.jpg"

    def face_sample_path(self, person_id: uuid.UUID, face_embedding_id: uuid.UUID) -> Path:
        return self.root / "people" / str(person_id) / "samples" / f"{face_embedding_id}.jpg"

    async def write(self, path: Path, data: bytes) -> int:
        return await asyncio.to_thread(self._write_sync, path, data)

    def _write_sync(self, path: Path, data: bytes) -> int:
        tmp_path = path.with_suffix(path.suffix + ".part")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path.write_bytes(data)
            tmp_path.replace(path)
        except OSError as exc:
            tmp_path.unlink(missing_ok=True)
            if exc.errno == errno.ENOSPC:
                raise StorageError(f"No space left to store {path.name}.") from exc
            if exc.errno in (errno.EACCES, errno.EPERM):
                raise StorageError(f"Permission denied writing {path.name}.") from exc
            raise StorageError(f"Failed to write {path.name}: {exc}") from exc
        return len(data)

    async def delete(self, path: Path) -> None:
        await asyncio.to_thread(self._delete_sync, path)

    def _delete_sync(self, path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise StorageError(f"Failed to delete {path.name}: {exc}") from exc


def get_clip_storage(root: Path) -> ClipStorage:
    return LocalClipStorage(root)
