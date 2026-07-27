"""People/face CRUD, clip-frame enrollment, and match lookups.

Frame extraction runs real ffmpeg against a synthetic clip (same "genuinely
exercised" policy as test_vehicles_service.py); face detection itself is
faked at app.biometrics.service's imported name, since detection accuracy
is already covered by test_biometrics_recognition.py — these tests are
about the orchestration (settings wiring, closest-bbox matching, thumbnail
persistence, cascade cleanup), not the ML.
"""

import asyncio
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.biometrics.service as biometrics_service
from app.ai.models import Analysis, AnalysisTier, SuspicionLabel
from app.biometrics.models import (
    ExecutionProviderPreference,
    FaceEmbedding,
    ModelPack,
    RecognizedFace,
)
from app.biometrics.recognition import DetectedFace
from app.biometrics.schemas import BiometricsSettingsUpdate, PersonUpdate
from app.biometrics.service import (
    REVERTED_LABEL,
    ClipFrameError,
    FaceNotFoundError,
    create_person,
    delete_person,
    detect_faces_in_clip_frame,
    enroll_face,
    extract_clip_frame,
    get_biometrics_settings,
    get_person,
    list_people,
    match_faces,
    report_false_positive,
    update_biometrics_settings,
    update_person,
)
from app.blink.models import BlinkAccount, Camera, Clip
from app.config import get_settings
from app.security.crypto import SecretBox
from app.storage.service import get_clip_storage

CACHE_DIR = Path("/fake/insightface/cache")


def _embedding(index: int) -> list[float]:
    """A 512-dim unit vector along axis `index` - exactly orthogonal to any
    other _embedding(other_index), so match scores are exact."""
    vec = [0.0] * 512
    vec[index] = 1.0
    return vec


def _fake_detect_faces(faces: list[DetectedFace]) -> Callable[..., list[DetectedFace]]:
    """A stand-in for app.biometrics.service's imported detect_faces that
    ignores whatever it's called with and always returns ``faces``."""

    def fake(*_args: object, **_kwargs: object) -> list[DetectedFace]:
        return faces

    return fake


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
    path = storage_dir / str(camera.id) / "clip.mp4"
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


# ------------------------------------------------------------------ settings


async def test_get_biometrics_settings_creates_default_row_on_first_access(
    app_session: AsyncSession,
) -> None:
    row = await get_biometrics_settings(app_session)
    assert row.enabled is False
    assert row.model_pack is ModelPack.BUFFALO_L
    assert row.execution_provider_preference is ExecutionProviderPreference.AUTO


async def test_update_biometrics_settings_persists_changes(app_session: AsyncSession) -> None:
    payload = BiometricsSettingsUpdate(
        enabled=True,
        model_pack=ModelPack.BUFFALO_SC,
        execution_provider_preference=ExecutionProviderPreference.CPU,
        recognition_threshold=0.6,
    )
    updated = await update_biometrics_settings(app_session, payload)
    assert updated.enabled is True
    assert updated.model_pack is ModelPack.BUFFALO_SC
    assert updated.execution_provider_preference is ExecutionProviderPreference.CPU
    assert updated.recognition_threshold == pytest.approx(0.6)

    reread = await get_biometrics_settings(app_session)
    assert reread.model_pack is ModelPack.BUFFALO_SC


# -------------------------------------------------------------- people CRUD


async def test_list_people_empty(app_session: AsyncSession) -> None:
    assert await list_people(app_session) == []


async def test_create_then_get_person(app_session: AsyncSession) -> None:
    created = await create_person(app_session, "Alex")
    assert created.name == "Alex"
    assert created.face_embeddings == []

    fetched = await get_person(app_session, created.id)
    assert fetched is not None
    assert fetched.name == "Alex"


async def test_get_person_returns_none_when_missing(app_session: AsyncSession) -> None:
    assert await get_person(app_session, uuid.uuid4()) is None


async def test_list_people_orders_by_name(app_session: AsyncSession) -> None:
    await create_person(app_session, "Zoe")
    await create_person(app_session, "Amir")
    people = await list_people(app_session)
    assert [p.name for p in people] == ["Amir", "Zoe"]


async def test_update_person_renames(app_session: AsyncSession) -> None:
    person = await create_person(app_session, "Old Name")
    renamed = await update_person(
        app_session, person, PersonUpdate(name="New Name", never_mark_suspicious=False)
    )
    assert renamed.name == "New Name"
    reread = await get_person(app_session, person.id)
    assert reread is not None
    assert reread.name == "New Name"


async def test_new_person_never_marks_suspicious_by_default(app_session: AsyncSession) -> None:
    person = await create_person(app_session, "Fresh Enrollment")
    assert person.never_mark_suspicious is False


async def test_update_person_can_set_never_mark_suspicious(app_session: AsyncSession) -> None:
    person = await create_person(app_session, "Trusted Neighbor")
    updated = await update_person(
        app_session, person, PersonUpdate(name=person.name, never_mark_suspicious=True)
    )
    assert updated.never_mark_suspicious is True
    reread = await get_person(app_session, person.id)
    assert reread is not None
    assert reread.never_mark_suspicious is True


async def test_update_person_can_clear_never_mark_suspicious(app_session: AsyncSession) -> None:
    person = await create_person(app_session, "Formerly Trusted")
    await update_person(
        app_session, person, PersonUpdate(name=person.name, never_mark_suspicious=True)
    )
    cleared = await update_person(
        app_session, person, PersonUpdate(name=person.name, never_mark_suspicious=False)
    )
    assert cleared.never_mark_suspicious is False


async def test_delete_person_removes_row_and_files(
    app_session: AsyncSession, tmp_path: Path
) -> None:
    storage = get_clip_storage(tmp_path)
    person = await create_person(app_session, "Departing")
    thumb_path = storage.person_thumbnail_path(person.id)
    thumb_path.parent.mkdir(parents=True, exist_ok=True)
    thumb_path.write_bytes(b"fake-profile-jpeg")

    embedding = FaceEmbedding(
        person_id=person.id,
        embedding=_embedding(0),
        thumbnail_path=str(storage.face_sample_path(person.id, uuid.uuid4())),
    )
    app_session.add(embedding)
    await app_session.commit()
    sample_path = storage.face_sample_path(person.id, embedding.id)
    sample_path.parent.mkdir(parents=True, exist_ok=True)
    sample_path.write_bytes(b"fake-sample-jpeg")

    loaded = await get_person(app_session, person.id)
    assert loaded is not None
    await delete_person(app_session, loaded, storage)

    assert await get_person(app_session, person.id) is None
    assert not thumb_path.exists()
    assert not sample_path.exists()


# ------------------------------------------------------------- clip frames


async def test_extract_clip_frame_raises_when_no_downloaded_clip(
    app_session: AsyncSession,
) -> None:
    with pytest.raises(ClipFrameError, match="No downloaded clip"):
        await extract_clip_frame(app_session, uuid.uuid4(), 1.0)


async def test_extract_clip_frame_raises_when_ffmpeg_cannot_read_file(
    app_session: AsyncSession, tmp_path: Path
) -> None:
    camera = await _make_camera(app_session)
    clip = await _make_downloaded_clip(app_session, camera, tmp_path, b"not a real video file")
    with pytest.raises(ClipFrameError, match="Could not extract"):
        await extract_clip_frame(app_session, clip.id, 0.5)


async def test_extract_clip_frame_returns_jpeg_bytes(
    app_session: AsyncSession, tmp_path: Path, sample_clip_bytes: bytes
) -> None:
    camera = await _make_camera(app_session)
    clip = await _make_downloaded_clip(app_session, camera, tmp_path, sample_clip_bytes)
    frame = await extract_clip_frame(app_session, clip.id, 0.5)
    assert frame[:2] == b"\xff\xd8"  # JPEG magic bytes


# ------------------------------------------------------------------ detect


async def test_detect_faces_in_clip_frame_passes_through_settings(
    app_session: AsyncSession,
    tmp_path: Path,
    sample_clip_bytes: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    camera = await _make_camera(app_session)
    clip = await _make_downloaded_clip(app_session, camera, tmp_path, sample_clip_bytes)
    settings_row = await get_biometrics_settings(app_session)

    captured: dict[str, object] = {}

    def fake_detect_faces(image_bytes: bytes, **kwargs: object) -> list[DetectedFace]:
        captured["image_bytes"] = image_bytes
        captured.update(kwargs)
        return [DetectedFace(bbox=(0.1, 0.1, 0.2, 0.2), confidence=0.9, embedding=_embedding(0))]

    monkeypatch.setattr(biometrics_service, "detect_faces", fake_detect_faces)

    result = await detect_faces_in_clip_frame(app_session, clip.id, 0.5, settings_row, CACHE_DIR)

    assert len(result) == 1
    assert captured["model_pack"] is settings_row.model_pack
    assert captured["provider_preference"] is settings_row.execution_provider_preference
    assert captured["model_cache_dir"] == CACHE_DIR
    assert captured["image_bytes"][:2] == b"\xff\xd8"  # type: ignore[index]


# ---------------------------------------------------------------- enroll


async def test_enroll_face_raises_when_nothing_detected(
    app_session: AsyncSession,
    tmp_path: Path,
    sample_clip_bytes: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    camera = await _make_camera(app_session)
    clip = await _make_downloaded_clip(app_session, camera, tmp_path, sample_clip_bytes)
    settings_row = await get_biometrics_settings(app_session)
    person = await create_person(app_session, "Nobody Detected")
    storage = get_clip_storage(tmp_path)

    monkeypatch.setattr(biometrics_service, "detect_faces", _fake_detect_faces([]))

    with pytest.raises(FaceNotFoundError):
        await enroll_face(
            app_session,
            storage,
            person,
            clip.id,
            0.5,
            (0.1, 0.1, 0.2, 0.2),
            settings_row,
            CACHE_DIR,
        )


async def test_enroll_face_raises_when_bbox_does_not_match_any_detection(
    app_session: AsyncSession,
    tmp_path: Path,
    sample_clip_bytes: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    camera = await _make_camera(app_session)
    clip = await _make_downloaded_clip(app_session, camera, tmp_path, sample_clip_bytes)
    settings_row = await get_biometrics_settings(app_session)
    person = await create_person(app_session, "Far Away")
    storage = get_clip_storage(tmp_path)

    far_face = DetectedFace(bbox=(0.1, 0.1, 0.2, 0.2), confidence=0.9, embedding=_embedding(0))
    monkeypatch.setattr(biometrics_service, "detect_faces", _fake_detect_faces([far_face]))

    with pytest.raises(FaceNotFoundError):
        await enroll_face(
            app_session,
            storage,
            person,
            clip.id,
            0.5,
            (0.8, 0.8, 0.1, 0.1),
            settings_row,
            CACHE_DIR,
        )


async def test_enroll_face_creates_embedding_and_backfills_person_thumbnail(
    app_session: AsyncSession,
    tmp_path: Path,
    sample_clip_bytes: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    camera = await _make_camera(app_session)
    clip = await _make_downloaded_clip(app_session, camera, tmp_path, sample_clip_bytes)
    settings_row = await get_biometrics_settings(app_session)
    person = await create_person(app_session, "Enrolled Person")
    storage = get_clip_storage(tmp_path)
    assert person.thumbnail_path is None

    target_face = DetectedFace(bbox=(0.3, 0.3, 0.2, 0.2), confidence=0.95, embedding=_embedding(3))
    monkeypatch.setattr(biometrics_service, "detect_faces", _fake_detect_faces([target_face]))

    embedding = await enroll_face(
        app_session,
        storage,
        person,
        clip.id,
        0.5,
        (0.3, 0.3, 0.2, 0.2),
        settings_row,
        CACHE_DIR,
    )

    assert embedding.person_id == person.id
    assert embedding.embedding == pytest.approx(_embedding(3))
    assert embedding.source_clip_id == clip.id
    assert embedding.source_frame_seconds == pytest.approx(0.5)
    assert Path(embedding.thumbnail_path).exists()
    assert Path(embedding.thumbnail_path).read_bytes()[:2] == b"\xff\xd8"

    await app_session.refresh(person)
    assert person.thumbnail_path is not None
    assert Path(person.thumbnail_path).exists()


async def test_enroll_face_does_not_overwrite_existing_person_thumbnail(
    app_session: AsyncSession,
    tmp_path: Path,
    sample_clip_bytes: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    camera = await _make_camera(app_session)
    clip = await _make_downloaded_clip(app_session, camera, tmp_path, sample_clip_bytes)
    settings_row = await get_biometrics_settings(app_session)
    person = await create_person(app_session, "Already Has Thumbnail")
    storage = get_clip_storage(tmp_path)
    existing_thumb = storage.person_thumbnail_path(person.id)
    existing_thumb.parent.mkdir(parents=True, exist_ok=True)
    existing_thumb.write_bytes(b"original-profile-jpeg")
    person.thumbnail_path = str(existing_thumb)
    await app_session.commit()

    target_face = DetectedFace(bbox=(0.3, 0.3, 0.2, 0.2), confidence=0.95, embedding=_embedding(4))
    monkeypatch.setattr(biometrics_service, "detect_faces", _fake_detect_faces([target_face]))

    await enroll_face(
        app_session, storage, person, clip.id, 0.5, (0.3, 0.3, 0.2, 0.2), settings_row, CACHE_DIR
    )

    assert existing_thumb.read_bytes() == b"original-profile-jpeg"


async def test_enroll_face_picks_the_closest_detection_when_several_present(
    app_session: AsyncSession,
    tmp_path: Path,
    sample_clip_bytes: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    camera = await _make_camera(app_session)
    clip = await _make_downloaded_clip(app_session, camera, tmp_path, sample_clip_bytes)
    settings_row = await get_biometrics_settings(app_session)
    person = await create_person(app_session, "Picks Correctly")
    storage = get_clip_storage(tmp_path)

    near = DetectedFace(bbox=(0.5, 0.5, 0.1, 0.1), confidence=0.9, embedding=_embedding(5))
    far = DetectedFace(bbox=(0.05, 0.05, 0.1, 0.1), confidence=0.9, embedding=_embedding(6))
    monkeypatch.setattr(biometrics_service, "detect_faces", _fake_detect_faces([far, near]))

    embedding = await enroll_face(
        app_session, storage, person, clip.id, 0.5, (0.5, 0.5, 0.1, 0.1), settings_row, CACHE_DIR
    )

    assert embedding.embedding == pytest.approx(_embedding(5))


# ------------------------------------------------------------------ matching


async def test_match_faces_returns_none_when_no_enrollments_exist(
    app_session: AsyncSession,
) -> None:
    query = DetectedFace(bbox=(0.0, 0.0, 0.1, 0.1), confidence=0.9, embedding=_embedding(0))
    assert await match_faces(app_session, [query], threshold=0.4) == [None]


async def test_match_faces_matches_by_closest_embedding_above_threshold(
    app_session: AsyncSession,
) -> None:
    person_a = await create_person(app_session, "Person A")
    person_b = await create_person(app_session, "Person B")
    app_session.add_all(
        [
            FaceEmbedding(person_id=person_a.id, embedding=_embedding(0), thumbnail_path="a.jpg"),
            FaceEmbedding(person_id=person_b.id, embedding=_embedding(1), thumbnail_path="b.jpg"),
        ]
    )
    await app_session.commit()

    query_a = DetectedFace(bbox=(0.0, 0.0, 0.1, 0.1), confidence=0.9, embedding=_embedding(0))
    query_unknown = DetectedFace(
        bbox=(0.2, 0.2, 0.1, 0.1), confidence=0.9, embedding=_embedding(42)
    )

    results = await match_faces(app_session, [query_a, query_unknown], threshold=0.5)

    assert results[0] is not None
    assert results[0].person_id == person_a.id
    assert results[0].score == pytest.approx(1.0)
    assert results[1] is None


async def test_match_faces_excludes_negative_samples(app_session: AsyncSession) -> None:
    person = await create_person(app_session, "Negative Sample Owner")
    app_session.add(
        FaceEmbedding(
            person_id=person.id,
            embedding=_embedding(7),
            thumbnail_path="neg.jpg",
            is_negative=True,
        )
    )
    await app_session.commit()

    query = DetectedFace(bbox=(0.0, 0.0, 0.1, 0.1), confidence=0.9, embedding=_embedding(7))
    assert await match_faces(app_session, [query], threshold=0.5) == [None]


# ------------------------------------------------------ report_false_positive


async def _make_analysis(
    session: AsyncSession, clip: Clip, entities: list[dict[str, object]]
) -> Analysis:
    analysis = Analysis(
        clip_id=clip.id,
        is_current=True,
        summary="Someone was on the porch.",
        suspicion_score=0.2,
        suspicion_label=SuspicionLabel.ROUTINE,
        tier=AnalysisTier.TIER1,
        detected_entities=entities,
    )
    session.add(analysis)
    await session.commit()
    await session.refresh(analysis)
    return analysis


async def test_report_false_positive_captures_negative_sample_and_reverts_label(
    app_session: AsyncSession,
    tmp_path: Path,
    sample_clip_bytes: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    camera = await _make_camera(app_session)
    clip = await _make_downloaded_clip(app_session, camera, tmp_path, sample_clip_bytes)
    settings_row = await get_biometrics_settings(app_session)
    storage = get_clip_storage(tmp_path)

    person = await create_person(app_session, "Wrongly Recognized")
    app_session.add(
        FaceEmbedding(person_id=person.id, embedding=_embedding(8), thumbnail_path="p.jpg")
    )
    app_session.add(RecognizedFace(clip_id=clip.id, person_id=person.id, confidence=0.91))
    analysis = await _make_analysis(
        app_session,
        clip,
        [
            {
                "type": "person",
                "label": "Wrongly Recognized",
                "confidence": 0.91,
                "bbox": [0.1, 0.1, 0.2, 0.2],
                "recognized_person_id": str(person.id),
            }
        ],
    )
    await app_session.commit()

    matching_face = DetectedFace(bbox=(0.1, 0.1, 0.2, 0.2), confidence=0.9, embedding=_embedding(8))
    monkeypatch.setattr(biometrics_service, "detect_faces", _fake_detect_faces([matching_face]))

    captured = await report_false_positive(
        app_session, storage, clip, person, settings_row, CACHE_DIR, keyframe_count=4
    )

    assert captured is True
    # Queried directly rather than via person.face_embeddings: that
    # collection was already loaded (empty) earlier in this session by
    # create_person's own refresh, and SQLAlchemy's identity map won't
    # re-populate an already-loaded collection just because a later
    # selectinload query runs - see delete_person's docstring for the same
    # gotcha.
    negative_samples = (
        (
            await app_session.execute(
                select(FaceEmbedding).where(
                    FaceEmbedding.person_id == person.id, FaceEmbedding.is_negative.is_(True)
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(negative_samples) == 1
    assert negative_samples[0].embedding == pytest.approx(_embedding(8))
    assert Path(negative_samples[0].thumbnail_path).exists()

    remaining = (
        await app_session.execute(select(RecognizedFace).where(RecognizedFace.clip_id == clip.id))
    ).scalar_one_or_none()
    assert remaining is None

    await app_session.refresh(analysis)
    assert analysis.detected_entities[0]["label"] == REVERTED_LABEL
    assert analysis.detected_entities[0]["recognized_person_id"] is None


async def test_report_false_positive_still_honored_when_face_not_found_again(
    app_session: AsyncSession,
    tmp_path: Path,
    sample_clip_bytes: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    camera = await _make_camera(app_session)
    clip = await _make_downloaded_clip(app_session, camera, tmp_path, sample_clip_bytes)
    settings_row = await get_biometrics_settings(app_session)
    storage = get_clip_storage(tmp_path)

    person = await create_person(app_session, "No Longer Detected")
    app_session.add(RecognizedFace(clip_id=clip.id, person_id=person.id, confidence=0.85))
    await app_session.commit()

    monkeypatch.setattr(biometrics_service, "detect_faces", _fake_detect_faces([]))

    captured = await report_false_positive(
        app_session, storage, clip, person, settings_row, CACHE_DIR, keyframe_count=4
    )

    assert captured is False
    remaining = (
        await app_session.execute(select(RecognizedFace).where(RecognizedFace.clip_id == clip.id))
    ).scalar_one_or_none()
    assert remaining is None


async def test_report_false_positive_only_touches_the_reported_persons_entity(
    app_session: AsyncSession,
    tmp_path: Path,
    sample_clip_bytes: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    camera = await _make_camera(app_session)
    clip = await _make_downloaded_clip(app_session, camera, tmp_path, sample_clip_bytes)
    settings_row = await get_biometrics_settings(app_session)
    storage = get_clip_storage(tmp_path)

    reported = await create_person(app_session, "Reported")
    other = await create_person(app_session, "Still Correct")
    analysis = await _make_analysis(
        app_session,
        clip,
        [
            {
                "type": "person",
                "label": "Reported",
                "confidence": 0.9,
                "bbox": [0.1, 0.1, 0.2, 0.2],
                "recognized_person_id": str(reported.id),
            },
            {
                "type": "person",
                "label": "Still Correct",
                "confidence": 0.9,
                "bbox": [0.6, 0.6, 0.2, 0.2],
                "recognized_person_id": str(other.id),
            },
        ],
    )
    monkeypatch.setattr(biometrics_service, "detect_faces", _fake_detect_faces([]))

    await report_false_positive(
        app_session, storage, clip, reported, settings_row, CACHE_DIR, keyframe_count=4
    )

    await app_session.refresh(analysis)
    assert analysis.detected_entities[0]["recognized_person_id"] is None
    assert analysis.detected_entities[1]["recognized_person_id"] == str(other.id)
    assert analysis.detected_entities[1]["label"] == "Still Correct"


async def test_report_false_positive_with_analysis_not_mentioning_person_is_a_no_op_edit(
    app_session: AsyncSession,
    tmp_path: Path,
    sample_clip_bytes: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A RecognizedFace can outlive the wording of detected_entities (e.g. a
    re-analysis ran between the recognition and the report) - the revert
    must be a safe no-op on the analysis in that case, not an error."""
    camera = await _make_camera(app_session)
    clip = await _make_downloaded_clip(app_session, camera, tmp_path, sample_clip_bytes)
    settings_row = await get_biometrics_settings(app_session)
    storage = get_clip_storage(tmp_path)

    person = await create_person(app_session, "Not Mentioned")
    app_session.add(RecognizedFace(clip_id=clip.id, person_id=person.id, confidence=0.9))
    analysis = await _make_analysis(
        app_session,
        clip,
        [{"type": "animal", "label": "A cat", "confidence": 0.7, "bbox": None}],
    )
    monkeypatch.setattr(biometrics_service, "detect_faces", _fake_detect_faces([]))

    await report_false_positive(
        app_session, storage, clip, person, settings_row, CACHE_DIR, keyframe_count=4
    )

    await app_session.refresh(analysis)
    assert analysis.detected_entities == [
        {"type": "animal", "label": "A cat", "confidence": 0.7, "bbox": None}
    ]


async def test_report_false_positive_raises_when_clip_not_downloaded(
    app_session: AsyncSession, tmp_path: Path
) -> None:
    camera = await _make_camera(app_session)
    clip = Clip(
        camera_id=camera.id,
        blink_clip_id="/media/never-downloaded.mp4",
        recorded_at=datetime(2026, 7, 20, tzinfo=UTC),
        raw_metadata={},
    )
    app_session.add(clip)
    await app_session.commit()
    settings_row = await get_biometrics_settings(app_session)
    person = await create_person(app_session, "Irrelevant")

    with pytest.raises(ClipFrameError):
        await report_false_positive(
            app_session,
            get_clip_storage(tmp_path),
            clip,
            person,
            settings_row,
            CACHE_DIR,
            keyframe_count=4,
        )


async def test_report_false_positive_with_no_current_analysis_only_removes_recognition(
    app_session: AsyncSession,
    tmp_path: Path,
    sample_clip_bytes: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    camera = await _make_camera(app_session)
    clip = await _make_downloaded_clip(app_session, camera, tmp_path, sample_clip_bytes)
    settings_row = await get_biometrics_settings(app_session)
    storage = get_clip_storage(tmp_path)
    person = await create_person(app_session, "Never Analyzed")
    app_session.add(RecognizedFace(clip_id=clip.id, person_id=person.id, confidence=0.8))
    await app_session.commit()

    monkeypatch.setattr(biometrics_service, "detect_faces", _fake_detect_faces([]))

    captured = await report_false_positive(
        app_session, storage, clip, person, settings_row, CACHE_DIR, keyframe_count=4
    )

    assert captured is False
