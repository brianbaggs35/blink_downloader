"""Vehicle CRUD and reference-frame capture (real ffmpeg, synthetic clip —
same "genuinely exercised" policy as test_worker_download.py)."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.blink.models import BlinkAccount, Camera, Clip
from app.config import get_settings
from app.security.crypto import SecretBox
from app.settings.service import set_storage_dir
from app.storage.service import get_clip_storage, sanitize_camera_folder_name
from app.vehicles.schemas import VehicleUpdate
from app.vehicles.service import (
    VehicleReferenceFrameError,
    capture_vehicle_reference_frame,
    delete_vehicle,
    get_vehicle,
    upsert_vehicle,
)


@pytest.fixture(scope="module")
def sample_clip_bytes(tmp_path_factory: pytest.TempPathFactory) -> bytes:
    path = tmp_path_factory.mktemp("clips") / "sample.mp4"

    async def make() -> None:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=2:size=64x64:rate=10",
            "-pix_fmt",
            "yuv420p",
            str(path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate()

    asyncio.run(make())
    return path.read_bytes()


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
    session: AsyncSession, camera: Camera, storage_dir: Path, content: bytes
) -> Clip:
    path = storage_dir / sanitize_camera_folder_name(camera.name) / "clip.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    clip = Clip(
        camera_id=camera.id,
        blink_clip_id="/media/clip1.mp4",
        recorded_at=datetime(2026, 7, 20, tzinfo=UTC),
        raw_metadata={},
        storage_path=str(path),
        downloaded_at=datetime.now(UTC),
    )
    session.add(clip)
    await session.commit()
    await session.refresh(clip)
    return clip


def make_update(**overrides: object) -> VehicleUpdate:
    defaults: dict[str, object] = {
        "description": "The blue sedan in the driveway",
        "outline_points": [(0.3, 0.5), (0.7, 0.5), (0.7, 0.8), (0.3, 0.8)],
    }
    defaults.update(overrides)
    return VehicleUpdate(**defaults)  # type: ignore[arg-type]


async def test_get_vehicle_returns_none_when_unregistered(app_session: AsyncSession) -> None:
    camera = await _make_camera(app_session)
    assert await get_vehicle(app_session, camera.id) is None


async def test_upsert_creates_then_updates(app_session: AsyncSession) -> None:
    camera = await _make_camera(app_session)
    created = await upsert_vehicle(app_session, camera.id, make_update())
    assert created.description == "The blue sedan in the driveway"
    assert created.outline_points == [[0.3, 0.5], [0.7, 0.5], [0.7, 0.8], [0.3, 0.8]]

    updated = await upsert_vehicle(
        app_session, camera.id, make_update(description="The red truck now", enabled=False)
    )
    assert updated.id == created.id  # same row, not a duplicate
    assert updated.description == "The red truck now"
    assert updated.enabled is False


async def test_delete_vehicle_removes_the_row_and_reference_frame(
    app_session: AsyncSession, tmp_path: Path
) -> None:
    camera = await _make_camera(app_session)
    vehicle = await upsert_vehicle(app_session, camera.id, make_update())
    storage = get_clip_storage(tmp_path)
    reference_path = storage.vehicle_reference_path(camera.name)
    reference_path.parent.mkdir(parents=True, exist_ok=True)
    reference_path.write_bytes(b"fake-jpeg")

    await delete_vehicle(app_session, vehicle, camera.name, storage)

    assert await get_vehicle(app_session, camera.id) is None
    assert not reference_path.exists()


async def test_capture_reference_frame_raises_with_no_downloaded_clips(
    app_session: AsyncSession, tmp_path: Path
) -> None:
    camera = await _make_camera(app_session)
    storage = get_clip_storage(tmp_path)
    with pytest.raises(VehicleReferenceFrameError, match="No downloaded clips"):
        await capture_vehicle_reference_frame(app_session, camera.id, camera.name, storage)


async def test_capture_reference_frame_writes_a_jpeg(
    app_session: AsyncSession, tmp_path: Path, sample_clip_bytes: bytes
) -> None:
    await set_storage_dir(app_session, str(tmp_path))
    camera = await _make_camera(app_session)
    await _make_downloaded_clip(app_session, camera, tmp_path, sample_clip_bytes)
    storage = get_clip_storage(tmp_path)

    destination = await capture_vehicle_reference_frame(
        app_session, camera.id, camera.name, storage
    )

    assert destination.exists()
    assert destination.read_bytes()[:2] == b"\xff\xd8"  # JPEG magic bytes
    assert destination == storage.vehicle_reference_path(camera.name)


async def test_capture_reference_frame_raises_when_ffmpeg_cannot_read_the_file(
    app_session: AsyncSession, tmp_path: Path
) -> None:
    camera = await _make_camera(app_session)
    await _make_downloaded_clip(app_session, camera, tmp_path, b"not a real video file")
    storage = get_clip_storage(tmp_path)

    with pytest.raises(VehicleReferenceFrameError, match="Could not capture"):
        await capture_vehicle_reference_frame(app_session, camera.id, camera.name, storage)
