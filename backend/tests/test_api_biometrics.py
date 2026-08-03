"""/api/biometrics/*: settings, renaming, and deletion are admin-only;
creating a person and enrolling a face are open to any signed-in user
(viewers can grow the household's face library, just not prune it); face
detection is faked at app.biometrics.service's imported name (real
insightface would trigger a model download) while frame extraction runs
real ffmpeg against a synthetic clip."""

import asyncio
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

import app.biometrics.service as biometrics_service
from app.biometrics.models import Person, RecognizedFace
from app.biometrics.recognition import DetectedFace, ModelLoadError
from app.blink.models import BlinkAccount, Camera, Clip
from app.config import get_settings
from app.security.crypto import SecretBox
from app.settings.service import set_storage_dir


def _embedding(index: int) -> list[float]:
    """A 512-dim unit vector along axis `index` - exactly orthogonal to any
    other _embedding(other_index), so match scores are exact."""
    vec = [0.0] * 512
    vec[index] = 1.0
    return vec


def _fake_detect_faces(faces: list[DetectedFace]) -> Callable[..., list[DetectedFace]]:
    def fake(*_args: object, **_kwargs: object) -> list[DetectedFace]:
        return faces

    return fake


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


async def _use_storage(app: FastAPI, tmp_path: Path) -> None:
    async with app.state.sessionmaker() as session:
        await set_storage_dir(session, str(tmp_path))


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


async def _make_person(app: FastAPI, name: str = "Alex") -> Person:
    async with app.state.sessionmaker() as session:
        person = Person(name=name)
        session.add(person)
        await session.commit()
        await session.refresh(person)
        return person


async def _recognize(app: FastAPI, clip: Clip, person: Person, confidence: float = 0.9) -> None:
    async with app.state.sessionmaker() as session:
        session.add(RecognizedFace(clip_id=clip.id, person_id=person.id, confidence=confidence))
        await session.commit()


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


# ------------------------------------------------------------------ settings


async def test_get_settings_requires_admin(viewer_client: AsyncClient) -> None:
    assert (await viewer_client.get("/api/biometrics/settings")).status_code == 403


async def test_get_settings_returns_defaults(admin_client: AsyncClient) -> None:
    response = await admin_client.get("/api/biometrics/settings")
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    assert body["model_pack"] == "buffalo_l"
    assert "available_providers" in body


async def test_put_settings_requires_admin(viewer_client: AsyncClient) -> None:
    response = await viewer_client.put("/api/biometrics/settings", json={"enabled": True})
    assert response.status_code == 403


async def test_put_settings_updates_and_persists(admin_client: AsyncClient) -> None:
    response = await admin_client.put(
        "/api/biometrics/settings",
        json={
            "enabled": True,
            "model_pack": "buffalo_sc",
            "execution_provider_preference": "cpu",
            "recognition_threshold": 0.55,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["model_pack"] == "buffalo_sc"
    assert body["recognition_threshold"] == 0.55

    reread = await admin_client.get("/api/biometrics/settings")
    assert reread.json()["model_pack"] == "buffalo_sc"


async def test_verify_model_requires_admin(viewer_client: AsyncClient) -> None:
    response = await viewer_client.post("/api/biometrics/settings/verify-model")
    assert response.status_code == 403


async def test_verify_model_starts_a_background_download_and_returns_immediately(
    admin_client: AsyncClient,
) -> None:
    """The actual download runs in a worker job (see
    test_worker_biometrics.py) - this route just flips the durable status
    and returns right away, so navigating away from Settings can't
    interrupt it."""
    response = await admin_client.post("/api/biometrics/settings/verify-model")
    assert response.status_code == 202
    body = response.json()
    assert body["model_download_status"] == "downloading"
    assert body["model_download_error"] is None

    reread = await admin_client.get("/api/biometrics/settings")
    assert reread.json()["model_download_status"] == "downloading"


async def test_verify_model_does_not_start_a_second_download_while_one_is_in_flight(
    admin_client: AsyncClient,
) -> None:
    first = await admin_client.post("/api/biometrics/settings/verify-model")
    assert first.status_code == 202

    second = await admin_client.post("/api/biometrics/settings/verify-model")
    assert second.status_code == 202
    assert second.json()["model_download_status"] == "downloading"


# -------------------------------------------------------------- people CRUD


async def test_list_people_requires_authentication(client: AsyncClient) -> None:
    assert (await client.get("/api/biometrics/people")).status_code == 401


async def test_list_people_empty(admin_client: AsyncClient) -> None:
    response = await admin_client.get("/api/biometrics/people")
    assert response.status_code == 200
    assert response.json() == []


async def test_viewer_can_create_person(viewer_client: AsyncClient) -> None:
    response = await viewer_client.post("/api/biometrics/people", json={"name": "Alex"})
    assert response.status_code == 201


async def test_create_person_then_list_and_get(admin_client: AsyncClient) -> None:
    create = await admin_client.post("/api/biometrics/people", json={"name": "Alex"})
    assert create.status_code == 201
    body = create.json()
    assert body["name"] == "Alex"
    assert body["face_count"] == 0
    assert body["has_thumbnail"] is False
    person_id = body["id"]

    listing = await admin_client.get("/api/biometrics/people")
    assert [p["name"] for p in listing.json()] == ["Alex"]

    fetched = await admin_client.get(f"/api/biometrics/people/{person_id}")
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "Alex"


async def test_create_person_rejects_blank_name(admin_client: AsyncClient) -> None:
    response = await admin_client.post("/api/biometrics/people", json={"name": ""})
    assert response.status_code == 422


async def test_get_person_404_for_unknown_id(admin_client: AsyncClient) -> None:
    response = await admin_client.get(f"/api/biometrics/people/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_update_person_requires_admin(viewer_client: AsyncClient, app: FastAPI) -> None:
    person = await _make_person(app)
    response = await viewer_client.put(
        f"/api/biometrics/people/{person.id}",
        json={"name": "New Name", "never_mark_suspicious": False},
    )
    assert response.status_code == 403


async def test_update_person_renames(admin_client: AsyncClient, app: FastAPI) -> None:
    person = await _make_person(app)
    response = await admin_client.put(
        f"/api/biometrics/people/{person.id}",
        json={"name": "New Name", "never_mark_suspicious": False},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "New Name"


async def test_update_person_requires_never_mark_suspicious(
    admin_client: AsyncClient, app: FastAPI
) -> None:
    person = await _make_person(app)
    response = await admin_client.put(
        f"/api/biometrics/people/{person.id}", json={"name": "New Name"}
    )
    assert response.status_code == 422


async def test_create_person_defaults_never_mark_suspicious_to_false(
    admin_client: AsyncClient,
) -> None:
    response = await admin_client.post("/api/biometrics/people", json={"name": "Alex"})
    assert response.json()["never_mark_suspicious"] is False


async def test_update_person_can_set_never_mark_suspicious(
    admin_client: AsyncClient, app: FastAPI
) -> None:
    person = await _make_person(app)
    response = await admin_client.put(
        f"/api/biometrics/people/{person.id}",
        json={"name": person.name, "never_mark_suspicious": True},
    )
    assert response.status_code == 200
    assert response.json()["never_mark_suspicious"] is True

    fetched = await admin_client.get(f"/api/biometrics/people/{person.id}")
    assert fetched.json()["never_mark_suspicious"] is True


async def test_delete_person_requires_admin(viewer_client: AsyncClient, app: FastAPI) -> None:
    person = await _make_person(app)
    assert (await viewer_client.delete(f"/api/biometrics/people/{person.id}")).status_code == 403


async def test_delete_person_404_for_unknown_id(admin_client: AsyncClient) -> None:
    response = await admin_client.delete(f"/api/biometrics/people/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_delete_person_removes_it(admin_client: AsyncClient, app: FastAPI) -> None:
    person = await _make_person(app)
    assert (await admin_client.delete(f"/api/biometrics/people/{person.id}")).status_code == 204
    assert (await admin_client.get(f"/api/biometrics/people/{person.id}")).status_code == 404


# ---------------------------------------------------------------- thumbnails


async def test_person_thumbnail_404_when_none_set(admin_client: AsyncClient, app: FastAPI) -> None:
    person = await _make_person(app)
    response = await admin_client.get(f"/api/biometrics/people/{person.id}/thumbnail")
    assert response.status_code == 404


async def test_list_person_faces_empty(admin_client: AsyncClient, app: FastAPI) -> None:
    person = await _make_person(app)
    response = await admin_client.get(f"/api/biometrics/people/{person.id}/faces")
    assert response.status_code == 200
    assert response.json() == []


async def test_face_thumbnail_404_for_unknown_face(admin_client: AsyncClient, app: FastAPI) -> None:
    person = await _make_person(app)
    response = await admin_client.get(
        f"/api/biometrics/people/{person.id}/faces/{uuid.uuid4()}/thumbnail"
    )
    assert response.status_code == 404


async def test_delete_face_requires_admin(viewer_client: AsyncClient, app: FastAPI) -> None:
    person = await _make_person(app)
    response = await viewer_client.delete(
        f"/api/biometrics/people/{person.id}/faces/{uuid.uuid4()}"
    )
    assert response.status_code == 403


async def test_delete_face_404_for_unknown_face_among_others(
    admin_client: AsyncClient,
    app: FastAPI,
    tmp_path: Path,
    sample_clip_bytes: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A person with an unrelated enrolled face still 404s for a different
    id, exercising the no-match branch of the lookup loop."""
    camera = await _make_camera(app)
    clip = await _make_downloaded_clip(app, camera, tmp_path, sample_clip_bytes)
    person = await _make_person(app)
    face = DetectedFace(bbox=(0.3, 0.3, 0.2, 0.2), confidence=0.9, embedding=_embedding(0))
    monkeypatch.setattr(biometrics_service, "detect_faces", _fake_detect_faces([face]))
    await admin_client.post(
        f"/api/biometrics/people/{person.id}/enroll",
        json={"clip_id": str(clip.id), "frame_seconds": 0.5, "bbox": [0.3, 0.3, 0.2, 0.2]},
    )

    response = await admin_client.delete(f"/api/biometrics/people/{person.id}/faces/{uuid.uuid4()}")
    assert response.status_code == 404


# ---------------------------------------------------------- clip frame/detect


async def test_clip_frame_409_when_not_downloaded(admin_client: AsyncClient) -> None:
    response = await admin_client.get(
        f"/api/biometrics/clips/{uuid.uuid4()}/frame", params={"frame_seconds": 0.5}
    )
    assert response.status_code == 409


async def test_clip_frame_returns_a_jpeg(
    admin_client: AsyncClient, app: FastAPI, tmp_path: Path, sample_clip_bytes: bytes
) -> None:
    camera = await _make_camera(app)
    clip = await _make_downloaded_clip(app, camera, tmp_path, sample_clip_bytes)
    response = await admin_client.get(
        f"/api/biometrics/clips/{clip.id}/frame", params={"frame_seconds": 0.5}
    )
    assert response.status_code == 200
    assert response.content[:2] == b"\xff\xd8"


async def test_detect_faces_409_when_not_downloaded(admin_client: AsyncClient) -> None:
    response = await admin_client.get(
        f"/api/biometrics/clips/{uuid.uuid4()}/detect-faces", params={"frame_seconds": 0.5}
    )
    assert response.status_code == 409


async def test_detect_faces_returns_detected_boxes(
    admin_client: AsyncClient,
    app: FastAPI,
    tmp_path: Path,
    sample_clip_bytes: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    camera = await _make_camera(app)
    clip = await _make_downloaded_clip(app, camera, tmp_path, sample_clip_bytes)
    face = DetectedFace(bbox=(0.1, 0.2, 0.3, 0.4), confidence=0.9, embedding=_embedding(0))
    monkeypatch.setattr(biometrics_service, "detect_faces", _fake_detect_faces([face]))

    response = await admin_client.get(
        f"/api/biometrics/clips/{clip.id}/detect-faces", params={"frame_seconds": 0.5}
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["confidence"] == pytest.approx(0.9)
    assert body[0]["bbox"] == pytest.approx([0.1, 0.2, 0.3, 0.4])
    assert "embedding" not in body[0]


# ---------------------------------------------------------------- enrollment


async def test_viewer_can_enroll_face(
    viewer_client: AsyncClient,
    app: FastAPI,
    tmp_path: Path,
    sample_clip_bytes: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    camera = await _make_camera(app)
    clip = await _make_downloaded_clip(app, camera, tmp_path, sample_clip_bytes)
    person = await _make_person(app)
    bbox = (0.3, 0.3, 0.2, 0.2)
    face = DetectedFace(bbox=bbox, confidence=0.9, embedding=_embedding(0))
    monkeypatch.setattr(biometrics_service, "detect_faces", _fake_detect_faces([face]))

    response = await viewer_client.post(
        f"/api/biometrics/people/{person.id}/enroll",
        json={"clip_id": str(clip.id), "frame_seconds": 0.5, "bbox": list(bbox)},
    )
    assert response.status_code == 200


async def test_enroll_404_for_unknown_person(admin_client: AsyncClient) -> None:
    response = await admin_client.post(
        f"/api/biometrics/people/{uuid.uuid4()}/enroll",
        json={"clip_id": str(uuid.uuid4()), "frame_seconds": 0.5, "bbox": [0.1, 0.1, 0.2, 0.2]},
    )
    assert response.status_code == 404


async def test_enroll_409_when_clip_not_downloaded(admin_client: AsyncClient, app: FastAPI) -> None:
    person = await _make_person(app)
    response = await admin_client.post(
        f"/api/biometrics/people/{person.id}/enroll",
        json={"clip_id": str(uuid.uuid4()), "frame_seconds": 0.5, "bbox": [0.1, 0.1, 0.2, 0.2]},
    )
    assert response.status_code == 409


async def test_enroll_404_when_bbox_does_not_match_any_detection(
    admin_client: AsyncClient,
    app: FastAPI,
    tmp_path: Path,
    sample_clip_bytes: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    camera = await _make_camera(app)
    clip = await _make_downloaded_clip(app, camera, tmp_path, sample_clip_bytes)
    person = await _make_person(app)
    monkeypatch.setattr(biometrics_service, "detect_faces", _fake_detect_faces([]))

    response = await admin_client.post(
        f"/api/biometrics/people/{person.id}/enroll",
        json={"clip_id": str(clip.id), "frame_seconds": 0.5, "bbox": [0.1, 0.1, 0.2, 0.2]},
    )
    assert response.status_code == 404


async def test_enroll_creates_a_face_sample_and_is_then_listed(
    admin_client: AsyncClient,
    app: FastAPI,
    tmp_path: Path,
    sample_clip_bytes: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    camera = await _make_camera(app)
    clip = await _make_downloaded_clip(app, camera, tmp_path, sample_clip_bytes)
    person = await _make_person(app)
    bbox = (0.3, 0.3, 0.2, 0.2)
    face = DetectedFace(bbox=bbox, confidence=0.9, embedding=_embedding(0))
    monkeypatch.setattr(biometrics_service, "detect_faces", _fake_detect_faces([face]))

    response = await admin_client.post(
        f"/api/biometrics/people/{person.id}/enroll",
        json={"clip_id": str(clip.id), "frame_seconds": 0.5, "bbox": list(bbox)},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["source_clip_id"] == str(clip.id)
    face_id = body["id"]

    faces = await admin_client.get(f"/api/biometrics/people/{person.id}/faces")
    assert [f["id"] for f in faces.json()] == [face_id]

    thumbnail = await admin_client.get(
        f"/api/biometrics/people/{person.id}/faces/{face_id}/thumbnail"
    )
    assert thumbnail.status_code == 200
    assert thumbnail.content[:2] == b"\xff\xd8"

    # First enrollment backfills the person's own thumbnail too.
    person_thumb = await admin_client.get(f"/api/biometrics/people/{person.id}/thumbnail")
    assert person_thumb.status_code == 200

    detail = await admin_client.get(f"/api/biometrics/people/{person.id}")
    assert detail.json()["face_count"] == 1
    assert detail.json()["has_thumbnail"] is True

    delete_response = await admin_client.delete(
        f"/api/biometrics/people/{person.id}/faces/{face_id}"
    )
    assert delete_response.status_code == 204
    faces_after = await admin_client.get(f"/api/biometrics/people/{person.id}/faces")
    assert faces_after.json() == []


# ------------------------------------------------------- report-false-positive


async def test_report_false_positive_requires_admin(
    viewer_client: AsyncClient, app: FastAPI
) -> None:
    person = await _make_person(app)
    response = await viewer_client.post(
        f"/api/biometrics/clips/{uuid.uuid4()}/people/{person.id}/report-false-positive"
    )
    assert response.status_code == 403


async def test_report_false_positive_404_for_unknown_clip(
    admin_client: AsyncClient, app: FastAPI
) -> None:
    person = await _make_person(app)
    response = await admin_client.post(
        f"/api/biometrics/clips/{uuid.uuid4()}/people/{person.id}/report-false-positive"
    )
    assert response.status_code == 404


async def test_report_false_positive_404_for_unknown_person(
    admin_client: AsyncClient, app: FastAPI, tmp_path: Path, sample_clip_bytes: bytes
) -> None:
    camera = await _make_camera(app)
    clip = await _make_downloaded_clip(app, camera, tmp_path, sample_clip_bytes)
    response = await admin_client.post(
        f"/api/biometrics/clips/{clip.id}/people/{uuid.uuid4()}/report-false-positive"
    )
    assert response.status_code == 404


async def test_report_false_positive_409_when_clip_not_downloaded(
    admin_client: AsyncClient, app: FastAPI
) -> None:
    camera = await _make_camera(app)
    async with app.state.sessionmaker() as session:
        clip = Clip(
            camera_id=camera.id,
            blink_clip_id="/media/never.mp4",
            recorded_at=datetime(2026, 7, 20, tzinfo=UTC),
            raw_metadata={},
        )
        session.add(clip)
        await session.commit()
        await session.refresh(clip)
    person = await _make_person(app)
    response = await admin_client.post(
        f"/api/biometrics/clips/{clip.id}/people/{person.id}/report-false-positive"
    )
    assert response.status_code == 409


async def test_report_false_positive_removes_recognition(
    admin_client: AsyncClient,
    app: FastAPI,
    tmp_path: Path,
    sample_clip_bytes: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    camera = await _make_camera(app)
    clip = await _make_downloaded_clip(app, camera, tmp_path, sample_clip_bytes)
    person = await _make_person(app, "Wrongly Recognized")
    await _recognize(app, clip, person)
    monkeypatch.setattr(biometrics_service, "detect_faces", _fake_detect_faces([]))

    response = await admin_client.post(
        f"/api/biometrics/clips/{clip.id}/people/{person.id}/report-false-positive"
    )
    assert response.status_code == 200
    assert response.json() == {"negative_sample_captured": False}


async def test_report_false_positive_502_when_model_load_fails(
    admin_client: AsyncClient,
    app: FastAPI,
    tmp_path: Path,
    sample_clip_bytes: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    camera = await _make_camera(app)
    clip = await _make_downloaded_clip(app, camera, tmp_path, sample_clip_bytes)
    person = await _make_person(app)
    await _recognize(app, clip, person)

    def _boom(*_args: object, **_kwargs: object) -> list[DetectedFace]:
        raise ModelLoadError("could not download the model")

    monkeypatch.setattr(biometrics_service, "detect_faces", _boom)
    response = await admin_client.post(
        f"/api/biometrics/clips/{clip.id}/people/{person.id}/report-false-positive"
    )
    assert response.status_code == 502


# ----------------------------------------------------- viewer read/write split


async def test_viewer_can_read_people_but_not_settings(
    viewer_client: AsyncClient, app: FastAPI
) -> None:
    person = await _make_person(app)
    assert (await viewer_client.get("/api/biometrics/people")).status_code == 200
    assert (await viewer_client.get(f"/api/biometrics/people/{person.id}")).status_code == 200
    assert (await viewer_client.get("/api/biometrics/settings")).status_code == 403
