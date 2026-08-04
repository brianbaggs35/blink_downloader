"""Local-disk clip storage: atomic writes, safe deletes, no partial files."""

import asyncio
import errno
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Protocol

from app.logs import get_logger

logger = get_logger(__name__)


class StorageError(Exception):
    """Writing, reading, or deleting clip bytes failed."""


class ClipStorage(Protocol):
    def clip_path(self, camera_name: str, clip_id: uuid.UUID, recorded_at: datetime) -> Path:
        """Where a clip's own video should be written - called exactly once,
        at download time, with its result immediately persisted as
        Clip.storage_path. Every other reader/deleter of an existing clip's
        file must use that persisted value instead of calling this again -
        a clip downloaded before this method's formula last changed (or
        before the owning camera was later renamed) would never resolve
        correctly through a fresh recompute."""
        ...

    def thumbnail_path(self, camera_name: str, clip_id: uuid.UUID, recorded_at: datetime) -> Path:
        """Same one-time-use-at-generation-time contract as clip_path above -
        the result is persisted as Clip.thumbnail_path. Existing readers use
        that persisted value, falling back to legacy_thumbnail_path below
        only for a clip generated before that column existed."""
        ...

    def legacy_thumbnail_path(self, camera_id: uuid.UUID, clip_id: uuid.UUID) -> Path:
        """The pre-migration flat thumbnail location (no date folder) - a
        fallback for a clip whose thumbnail_path column is null because it
        was generated before that column existed, frozen exactly as that
        historical layout was, regardless of any future clip_path change -
        including today's switch to a name-keyed camera folder below, which
        deliberately does not apply here."""
        ...

    def vehicle_reference_path(self, camera_name: str) -> Path: ...

    def camera_preview_path(self, camera_name: str) -> Path: ...

    def person_thumbnail_path(self, person_id: uuid.UUID) -> Path: ...

    def face_sample_path(self, person_id: uuid.UUID, face_embedding_id: uuid.UUID) -> Path: ...

    def sync_module_clip_path(
        self, sync_module_id: uuid.UUID, item_id: uuid.UUID, recorded_at: datetime
    ) -> Path:
        """Where a Sync Module local-storage item's downloaded video should
        be written - same one-time-use-at-download-time contract as
        clip_path above, persisted as SyncModuleLocalItem.storage_path."""
        ...

    async def write(self, path: Path, data: bytes) -> int:
        """Write ``data`` to ``path`` atomically. Returns the byte count."""
        ...

    async def delete(self, path: Path) -> None:
        """Remove ``path``. Not an error if it's already gone."""
        ...


def sanitize_camera_folder_name(camera_name: str) -> str:
    """A camera's display name, made safe as a single path segment - as
    opposed to the clip/thumbnail/person/face filenames elsewhere in this
    module, which are always our own UUIDs and need no sanitizing at all.
    Blink camera names are free text an account holder can set to anything,
    so this can't assume filesystem-safe input the way the rest of this
    module does. "/" would otherwise be read as a subdirectory separator;
    Windows-reserved characters are stripped too since these volumes are
    routinely browsed from a Windows Docker Desktop host. Falls back to
    "camera" for a name that sanitizes down to nothing (e.g. one that was
    only "/"s), rather than collapsing to the storage root itself."""
    cleaned = re.sub(r'[/\\<>:"|?*\x00-\x1f]', "-", camera_name).strip(" .")
    return cleaned or "camera"


class LocalClipStorage:
    def __init__(self, root: Path) -> None:
        self.root = root

    def clip_path(self, camera_name: str, clip_id: uuid.UUID, recorded_at: datetime) -> Path:
        # camera/date (not date/camera) matches the Library bulk-ZIP
        # export's existing arcname convention (app.api.clips._clip_arcname)
        # - one grouping convention across the app, not two.
        return (
            self.root
            / sanitize_camera_folder_name(camera_name)
            / f"{recorded_at:%Y-%m-%d}"
            / f"{clip_id}.mp4"
        )

    def thumbnail_path(self, camera_name: str, clip_id: uuid.UUID, recorded_at: datetime) -> Path:
        return (
            self.root
            / sanitize_camera_folder_name(camera_name)
            / f"{recorded_at:%Y-%m-%d}"
            / f"{clip_id}.jpg"
        )

    def legacy_thumbnail_path(self, camera_id: uuid.UUID, clip_id: uuid.UUID) -> Path:
        return self.root / str(camera_id) / f"{clip_id}.jpg"

    def vehicle_reference_path(self, camera_name: str) -> Path:
        return self.root / sanitize_camera_folder_name(camera_name) / "vehicle-reference.jpg"

    def camera_preview_path(self, camera_name: str) -> Path:
        return self.root / sanitize_camera_folder_name(camera_name) / "preview.jpg"

    def person_thumbnail_path(self, person_id: uuid.UUID) -> Path:
        return self.root / "people" / str(person_id) / "profile.jpg"

    def face_sample_path(self, person_id: uuid.UUID, face_embedding_id: uuid.UUID) -> Path:
        return self.root / "people" / str(person_id) / "samples" / f"{face_embedding_id}.jpg"

    def sync_module_clip_path(
        self, sync_module_id: uuid.UUID, item_id: uuid.UUID, recorded_at: datetime
    ) -> Path:
        return (
            self.root
            / "sync-module"
            / str(sync_module_id)
            / f"{recorded_at:%Y-%m-%d}"
            / f"{item_id}.mp4"
        )

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
