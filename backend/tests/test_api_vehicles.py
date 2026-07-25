"""/api/vehicles/*: outline configuration (admin-only) and viewing (any
signed-in household member)."""

import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.blink.models import BlinkAccount, Camera, Clip
from app.config import get_settings
from app.security.crypto import SecretBox
from app.settings.service import set_storage_dir
from app.vehicles.models import ProximityEvent, Vehicle

VALID_OUTLINE = [[0.3, 0.5], [0.7, 0.5], [0.7, 0.8], [0.3, 0.8]]


async def _make_camera(app: FastAPI, name: str = "Driveway") -> Camera:
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


async def _make_vehicle(app: FastAPI, camera: Camera, **overrides: object) -> Vehicle:
    async with app.state.sessionmaker() as session:
        defaults: dict[str, object] = {
            "camera_id": camera.id,
            "description": "The blue sedan",
            "outline_points": VALID_OUTLINE,
        }
        defaults.update(overrides)
        vehicle = Vehicle(**defaults)  # type: ignore[arg-type]
        session.add(vehicle)
        await session.commit()
        await session.refresh(vehicle)
        return vehicle


async def _make_downloaded_clip(app: FastAPI, camera: Camera, tmp_path: Path, data: bytes) -> Clip:
    await _use_storage(app, tmp_path)
    path = tmp_path / str(camera.id) / "clip.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    async with app.state.sessionmaker() as session:
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
        return clip


async def _use_storage(app: FastAPI, tmp_path: Path) -> None:
    async with app.state.sessionmaker() as session:
        await set_storage_dir(session, str(tmp_path))


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


# ---------------------------------------------------------------------- list


async def test_list_requires_authentication(client: AsyncClient) -> None:
    assert (await client.get("/api/vehicles")).status_code == 401


async def test_list_is_empty_with_no_vehicles(admin_client: AsyncClient) -> None:
    response = await admin_client.get("/api/vehicles")
    assert response.status_code == 200
    assert response.json() == []


async def test_list_includes_camera_name(admin_client: AsyncClient, app: FastAPI) -> None:
    camera = await _make_camera(app)
    await _make_vehicle(app, camera)
    response = await admin_client.get("/api/vehicles")
    body = response.json()
    assert len(body) == 1
    assert body[0]["camera_name"] == "Driveway"
    assert body[0]["outline_points"] == VALID_OUTLINE


# ----------------------------------------------------------------------- get


async def test_get_404_for_unknown_camera(admin_client: AsyncClient) -> None:
    response = await admin_client.get(f"/api/vehicles/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_get_404_when_camera_has_no_vehicle(admin_client: AsyncClient, app: FastAPI) -> None:
    camera = await _make_camera(app)
    response = await admin_client.get(f"/api/vehicles/{camera.id}")
    assert response.status_code == 404


async def test_get_returns_the_vehicle(admin_client: AsyncClient, app: FastAPI) -> None:
    camera = await _make_camera(app)
    await _make_vehicle(app, camera)
    response = await admin_client.get(f"/api/vehicles/{camera.id}")
    assert response.status_code == 200
    assert response.json()["description"] == "The blue sedan"
    assert response.json()["has_reference_frame"] is False


# ----------------------------------------------------------------------- put


async def test_put_requires_admin(viewer_client: AsyncClient, app: FastAPI) -> None:
    camera = await _make_camera(app)
    response = await viewer_client.put(
        f"/api/vehicles/{camera.id}",
        json={"description": "x", "outline_points": VALID_OUTLINE},
    )
    assert response.status_code == 403


async def test_put_404_for_unknown_camera(admin_client: AsyncClient) -> None:
    response = await admin_client.put(
        f"/api/vehicles/{uuid.uuid4()}",
        json={"description": "x", "outline_points": VALID_OUTLINE},
    )
    assert response.status_code == 404


async def test_put_creates_and_then_updates(admin_client: AsyncClient, app: FastAPI) -> None:
    camera = await _make_camera(app)
    create = await admin_client.put(
        f"/api/vehicles/{camera.id}",
        json={
            "description": "The blue sedan",
            "outline_points": VALID_OUTLINE,
            "estimated_length_feet": 16.0,
            "distance_threshold_feet": 8.0,
        },
    )
    assert create.status_code == 200
    body = create.json()
    assert body["estimated_length_feet"] == 16.0
    vehicle_id = body["id"]

    update = await admin_client.put(
        f"/api/vehicles/{camera.id}",
        json={"description": "The red truck", "outline_points": VALID_OUTLINE},
    )
    assert update.status_code == 200
    assert update.json()["id"] == vehicle_id
    assert update.json()["description"] == "The red truck"


async def test_put_rejects_too_few_outline_points(admin_client: AsyncClient, app: FastAPI) -> None:
    camera = await _make_camera(app)
    response = await admin_client.put(
        f"/api/vehicles/{camera.id}",
        json={"description": "x", "outline_points": [[0.3, 0.5], [0.7, 0.5]]},
    )
    assert response.status_code == 422


async def test_put_rejects_non_normalized_points(admin_client: AsyncClient, app: FastAPI) -> None:
    camera = await _make_camera(app)
    response = await admin_client.put(
        f"/api/vehicles/{camera.id}",
        json={"description": "x", "outline_points": [[1.5, 0.5], [0.7, 0.5], [0.7, 0.8]]},
    )
    assert response.status_code == 422


async def test_put_rejects_out_of_range_threshold(admin_client: AsyncClient, app: FastAPI) -> None:
    camera = await _make_camera(app)
    response = await admin_client.put(
        f"/api/vehicles/{camera.id}",
        json={
            "description": "x",
            "outline_points": VALID_OUTLINE,
            "distance_threshold_feet": -1,
        },
    )
    assert response.status_code == 422


# -------------------------------------------------------------------- delete


async def test_delete_requires_admin(viewer_client: AsyncClient, app: FastAPI) -> None:
    camera = await _make_camera(app)
    await _make_vehicle(app, camera)
    assert (await viewer_client.delete(f"/api/vehicles/{camera.id}")).status_code == 403


async def test_delete_404_when_none_registered(admin_client: AsyncClient, app: FastAPI) -> None:
    camera = await _make_camera(app)
    assert (await admin_client.delete(f"/api/vehicles/{camera.id}")).status_code == 404


async def test_delete_removes_the_vehicle(admin_client: AsyncClient, app: FastAPI) -> None:
    camera = await _make_camera(app)
    await _make_vehicle(app, camera)
    assert (await admin_client.delete(f"/api/vehicles/{camera.id}")).status_code == 204
    assert (await admin_client.get(f"/api/vehicles/{camera.id}")).status_code == 404


# ------------------------------------------------------------- reference frame


async def test_capture_reference_frame_requires_admin(
    viewer_client: AsyncClient, app: FastAPI
) -> None:
    camera = await _make_camera(app)
    response = await viewer_client.post(f"/api/vehicles/{camera.id}/reference-frame")
    assert response.status_code == 403


async def test_capture_reference_frame_404_for_unknown_camera(admin_client: AsyncClient) -> None:
    response = await admin_client.post(f"/api/vehicles/{uuid.uuid4()}/reference-frame")
    assert response.status_code == 404


async def test_capture_reference_frame_409_with_no_downloaded_clips(
    admin_client: AsyncClient, app: FastAPI
) -> None:
    camera = await _make_camera(app)
    response = await admin_client.post(f"/api/vehicles/{camera.id}/reference-frame")
    assert response.status_code == 409


async def test_capture_reference_frame_and_fetch_it(
    admin_client: AsyncClient, app: FastAPI, tmp_path: Path, sample_clip_bytes: bytes
) -> None:
    camera = await _make_camera(app)
    await _make_downloaded_clip(app, camera, tmp_path, sample_clip_bytes)

    capture = await admin_client.post(f"/api/vehicles/{camera.id}/reference-frame")
    assert capture.status_code == 204

    fetched = await admin_client.get(f"/api/vehicles/{camera.id}/reference-frame")
    assert fetched.status_code == 200
    assert fetched.content[:2] == b"\xff\xd8"

    # Reflected on the vehicle read once one exists.
    await _make_vehicle(app, camera)
    detail = await admin_client.get(f"/api/vehicles/{camera.id}")
    assert detail.json()["has_reference_frame"] is True


async def test_get_reference_frame_404_when_none_captured(
    admin_client: AsyncClient, app: FastAPI
) -> None:
    camera = await _make_camera(app)
    response = await admin_client.get(f"/api/vehicles/{camera.id}/reference-frame")
    assert response.status_code == 404


# -------------------------------------------------------------- proximity events


async def test_proximity_events_404_when_no_vehicle(
    admin_client: AsyncClient, app: FastAPI
) -> None:
    camera = await _make_camera(app)
    response = await admin_client.get(f"/api/vehicles/{camera.id}/proximity-events")
    assert response.status_code == 404


async def test_proximity_events_lists_newest_first(
    admin_client: AsyncClient, app: FastAPI, tmp_path: Path
) -> None:
    camera = await _make_camera(app)
    vehicle = await _make_vehicle(app, camera)
    clip = await _make_downloaded_clip(app, camera, tmp_path, b"irrelevant-bytes")
    async with app.state.sessionmaker() as session:
        session.add(
            ProximityEvent(
                vehicle_id=vehicle.id,
                clip_id=clip.id,
                distance_feet=3.0,
                error_margin_feet=1.0,
                occurred_at=datetime(2026, 7, 20, 12, 0, tzinfo=UTC),
            )
        )
        session.add(
            ProximityEvent(
                vehicle_id=vehicle.id,
                clip_id=clip.id,
                distance_feet=5.0,
                error_margin_feet=1.5,
                occurred_at=datetime(2026, 7, 20, 14, 0, tzinfo=UTC),
            )
        )
        await session.commit()

    response = await admin_client.get(f"/api/vehicles/{camera.id}/proximity-events")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert body[0]["distance_feet"] == 5.0  # most recent first


# --------------------------------------------------------- viewer can read only


async def test_viewer_can_list_get_and_view_reference_frame(
    viewer_client: AsyncClient, app: FastAPI
) -> None:
    camera = await _make_camera(app)
    await _make_vehicle(app, camera)
    assert (await viewer_client.get("/api/vehicles")).status_code == 200
    assert (await viewer_client.get(f"/api/vehicles/{camera.id}")).status_code == 200
    events_response = await viewer_client.get(f"/api/vehicles/{camera.id}/proximity-events")
    assert events_response.status_code == 200
