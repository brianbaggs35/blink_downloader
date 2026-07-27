"""archive_clip_job/restore_clip_job: the worker entrypoints that resolve a
clip + the configured local storage dir, then delegate to
app.integrations.archive's orchestration functions.

The cloud side is faked at build_s3_client (the name app.integrations.archive
itself imports and calls) - never a real S3 call."""

# Untyped monkeypatch.setattr(str, lambda) call sites below - same as
# test_integrations_cloud.py.
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownLambdaType=false

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.blink.models import BlinkAccount, Camera, Clip, StorageBackend
from app.config import get_settings
from app.integrations.cloud import CloudStorageError
from app.security.crypto import SecretBox
from app.settings.service import set_storage_dir
from app.worker.tasks.archive import archive_clip_job, restore_clip_job


class _FakeCloudClient:
    def __init__(self, *, raise_on: set[str] | None = None) -> None:
        self.raise_on = raise_on or set()

    async def upload(self, name: str, data: bytes) -> str:
        if "upload" in self.raise_on:
            raise CloudStorageError("upload boom")
        return f"remote/{name}"

    async def download(self, key: str) -> bytes:
        if "download" in self.raise_on:
            raise CloudStorageError("download boom")
        return b"remote-bytes"

    async def delete(self, key: str) -> None:
        pass

    async def test_connection(self) -> None:
        pass


async def _make_camera(ctx: dict[str, Any]) -> Camera:
    async with ctx["sessionmaker"]() as session:
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
            blink_camera_id="cam-1",
            blink_network_id="net-1",
            name="Driveway",
            camera_type="catalina",
        )
        session.add(camera)
        await session.commit()
        await session.refresh(camera)
        return camera


async def _make_local_clip(ctx: dict[str, Any], camera: Camera, tmp_path: Path) -> Clip:
    async with ctx["sessionmaker"]() as session:
        await set_storage_dir(session, str(tmp_path))
        clip = Clip(
            camera_id=camera.id,
            blink_clip_id="/media/x.mp4",
            recorded_at=datetime(2026, 7, 20, tzinfo=UTC),
            raw_metadata={},
        )
        session.add(clip)
        await session.commit()
        await session.refresh(clip)

        path = tmp_path / str(camera.id) / f"{clip.id}.mp4"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"clip-bytes")
        clip.storage_path = str(path)
        clip.filename = path.name
        clip.file_size_bytes = 10
        clip.downloaded_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(clip)
        return clip


async def _make_archived_clip(ctx: dict[str, Any], camera: Camera, tmp_path: Path) -> Clip:
    async with ctx["sessionmaker"]() as session:
        await set_storage_dir(session, str(tmp_path))
        clip = Clip(
            camera_id=camera.id,
            blink_clip_id="/media/y.mp4",
            recorded_at=datetime(2026, 7, 20, tzinfo=UTC),
            raw_metadata={},
            storage_backend=StorageBackend.S3,
            storage_path="remote/y.mp4",
        )
        session.add(clip)
        await session.commit()
        await session.refresh(clip)
        clip.filename = "y.mp4"
        clip.file_size_bytes = 10
        clip.downloaded_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(clip)
        return clip


# --------------------------------------------------------------- archive_clip


async def test_archive_clip_job_returns_clip_not_found(worker_ctx: dict[str, Any]) -> None:
    result = await archive_clip_job(worker_ctx, str(uuid.uuid4()), "s3")
    assert result == "clip_not_found"


async def test_archive_clip_job_succeeds(
    monkeypatch: pytest.MonkeyPatch, worker_ctx: dict[str, Any], tmp_path: Path
) -> None:
    camera = await _make_camera(worker_ctx)
    clip = await _make_local_clip(worker_ctx, camera, tmp_path)
    monkeypatch.setattr(
        "app.integrations.archive.build_s3_client", lambda *_a, **_kw: _FakeCloudClient()
    )

    result = await archive_clip_job(worker_ctx, str(clip.id), "s3")
    assert result == "ok"

    async with worker_ctx["sessionmaker"]() as session:
        refreshed = await session.get(Clip, clip.id)
        assert refreshed is not None
        assert refreshed.storage_backend == StorageBackend.S3


async def test_archive_clip_job_reports_archive_errors(
    monkeypatch: pytest.MonkeyPatch, worker_ctx: dict[str, Any], tmp_path: Path
) -> None:
    camera = await _make_camera(worker_ctx)
    clip = await _make_local_clip(worker_ctx, camera, tmp_path)
    monkeypatch.setattr("app.integrations.archive.build_s3_client", lambda *_a, **_kw: None)

    result = await archive_clip_job(worker_ctx, str(clip.id), "s3")
    assert result.startswith("failed:")


# --------------------------------------------------------------- restore_clip


async def test_restore_clip_job_returns_clip_not_found(worker_ctx: dict[str, Any]) -> None:
    result = await restore_clip_job(worker_ctx, str(uuid.uuid4()))
    assert result == "clip_not_found"


async def test_restore_clip_job_succeeds(
    monkeypatch: pytest.MonkeyPatch, worker_ctx: dict[str, Any], tmp_path: Path
) -> None:
    camera = await _make_camera(worker_ctx)
    clip = await _make_archived_clip(worker_ctx, camera, tmp_path)
    monkeypatch.setattr(
        "app.integrations.archive.build_s3_client", lambda *_a, **_kw: _FakeCloudClient()
    )

    result = await restore_clip_job(worker_ctx, str(clip.id))
    assert result == "ok"

    async with worker_ctx["sessionmaker"]() as session:
        refreshed = await session.get(Clip, clip.id)
        assert refreshed is not None
        assert refreshed.storage_backend == StorageBackend.LOCAL


async def test_restore_clip_job_reports_archive_errors(
    monkeypatch: pytest.MonkeyPatch, worker_ctx: dict[str, Any], tmp_path: Path
) -> None:
    camera = await _make_camera(worker_ctx)
    clip = await _make_archived_clip(worker_ctx, camera, tmp_path)
    monkeypatch.setattr("app.integrations.archive.build_s3_client", lambda *_a, **_kw: None)

    result = await restore_clip_job(worker_ctx, str(clip.id))
    assert result.startswith("failed:")
