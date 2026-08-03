"""People/face CRUD, clip-frame enrollment, and match lookups for the local
face-recognition pipeline.

Nothing here (or in app.biometrics.recognition) ever makes a network call —
see app.biometrics.models's module docstring for why that matters. Settings
values that come from app.config (e.g. the model cache directory) are
resolved by callers and passed in explicitly, the same layering as
app.vehicles.service/app.storage.service.
"""

import asyncio
import uuid
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ai.models import Analysis
from app.biometrics.models import (
    SINGLETON_ID,
    BiometricsSettings,
    FaceEmbedding,
    ModelDownloadStatus,
    Person,
    RecognizedFace,
)
from app.biometrics.recognition import (
    DetectedFace,
    FaceMatch,
    best_match,
    crop_face_thumbnail,
    detect_faces,
    ensure_model_ready,
)
from app.biometrics.schemas import BiometricsSettingsUpdate, PersonUpdate
from app.blink.models import Clip
from app.storage.service import ClipStorage
from app.video.ffmpeg import extract_biometrics_frame, extract_keyframes

_BBOX_MATCH_TOLERANCE = 0.05
"""Max per-coordinate drift allowed between the bbox a client echoes back
from a preview response and what re-detecting the same frame finds. Should
be ~0 in practice (detection is deterministic on identical frame bytes) -
this only guards the pathological case of the frame changing between
preview and enroll (e.g. the clip file was replaced mid-flow)."""


class ClipFrameError(Exception):
    """No downloaded clip file to extract a frame from, or ffmpeg couldn't
    extract one at the requested time."""


class FaceNotFoundError(Exception):
    """No freshly-detected face in the frame matches the bbox the caller
    asked to enroll."""


async def get_biometrics_settings(session: AsyncSession) -> BiometricsSettings:
    row = await session.get(BiometricsSettings, SINGLETON_ID)
    if row is None:
        row = BiometricsSettings(id=SINGLETON_ID)
        session.add(row)
        await session.flush()
    return row


async def update_biometrics_settings(
    session: AsyncSession, payload: BiometricsSettingsUpdate
) -> BiometricsSettings:
    row = await get_biometrics_settings(session)
    # A previous "ready" (or "error") result only means something for the
    # exact model pack + provider preference it was verified against -
    # switching either one stops the old result from being meaningful,
    # so it resets rather than keeps showing a now-unrelated status.
    if (
        row.model_pack != payload.model_pack
        or row.execution_provider_preference != payload.execution_provider_preference
    ):
        row.model_download_status = ModelDownloadStatus.IDLE
        row.model_download_error = None
        row.model_download_providers = []
    row.enabled = payload.enabled
    row.model_pack = payload.model_pack
    row.execution_provider_preference = payload.execution_provider_preference
    row.recognition_threshold = payload.recognition_threshold
    await session.commit()
    await session.refresh(row)
    return row


async def start_model_download(
    session: AsyncSession, biometrics_settings: BiometricsSettings
) -> BiometricsSettings:
    """Flips the singleton row to "downloading" and returns immediately -
    the actual download runs in the background (see
    app.worker.tasks.biometrics), so navigating away from Settings can't
    interrupt it. Callers (the API route) enqueue the worker job themselves
    right after calling this."""
    biometrics_settings.model_download_status = ModelDownloadStatus.DOWNLOADING
    biometrics_settings.model_download_error = None
    await session.commit()
    await session.refresh(biometrics_settings)
    return biometrics_settings


async def download_biometrics_model(
    session: AsyncSession, biometrics_settings: BiometricsSettings, model_cache_dir: Path
) -> None:
    """Downloads (if needed) and loads the configured model pack, so an
    admin gets a clear pass/fail right after choosing a model in Settings
    rather than discovering a download problem during the next real clip
    analysis. Sets the row to "ready" with the resolved providers on
    success. Raises ModelLoadError (see app.biometrics.recognition) on
    failure - the caller (a worker job) owns translating that into
    model_download_status/model_download_error, the same split as
    app.sync_module.service.refresh_local_storage_manifest."""
    providers = await asyncio.to_thread(
        ensure_model_ready,
        biometrics_settings.model_pack,
        biometrics_settings.execution_provider_preference,
        model_cache_dir,
    )
    biometrics_settings.model_download_status = ModelDownloadStatus.READY
    biometrics_settings.model_download_providers = providers
    biometrics_settings.model_download_error = None
    await session.commit()


async def list_people(session: AsyncSession) -> Sequence[Person]:
    stmt = select(Person).options(selectinload(Person.face_embeddings)).order_by(Person.name)
    return (await session.execute(stmt)).scalars().all()


async def get_person(session: AsyncSession, person_id: uuid.UUID) -> Person | None:
    stmt = (
        select(Person).where(Person.id == person_id).options(selectinload(Person.face_embeddings))
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def create_person(session: AsyncSession, name: str) -> Person:
    person = Person(name=name)
    session.add(person)
    await session.commit()
    await session.refresh(person, attribute_names=["face_embeddings"])
    return person


async def update_person(session: AsyncSession, person: Person, payload: PersonUpdate) -> Person:
    person.name = payload.name
    person.never_mark_suspicious = payload.never_mark_suspicious
    await session.commit()
    await session.refresh(person)
    return person


async def delete_person(session: AsyncSession, person: Person, storage: ClipStorage) -> None:
    """Queries embedding ids fresh rather than trusting ``person.face_embeddings``
    to be loaded/current - the DB rows cascade on their own, but the
    thumbnail files on disk need explicit cleanup same as a vehicle's
    reference frame, and a relationship collection populated earlier in a
    longer-lived session can be stale by the time this runs."""
    await storage.delete(storage.person_thumbnail_path(person.id))
    stmt = select(FaceEmbedding.id).where(FaceEmbedding.person_id == person.id)
    embedding_ids = (await session.execute(stmt)).scalars().all()
    for embedding_id in embedding_ids:
        await storage.delete(storage.face_sample_path(person.id, embedding_id))
    await session.delete(person)
    await session.commit()


async def extract_clip_frame(
    session: AsyncSession, clip_id: uuid.UUID, frame_seconds: float
) -> bytes:
    clip = await session.get(Clip, clip_id)
    if clip is None or not clip.storage_path:
        raise ClipFrameError("No downloaded clip file to extract a frame from.")
    frame = await extract_biometrics_frame(Path(clip.storage_path), frame_seconds)
    if frame is None:
        raise ClipFrameError("Could not extract a frame at that time.")
    return frame


async def detect_faces_in_clip_frame(
    session: AsyncSession,
    clip_id: uuid.UUID,
    frame_seconds: float,
    biometrics_settings: BiometricsSettings,
    model_cache_dir: Path,
) -> list[DetectedFace]:
    frame = await extract_clip_frame(session, clip_id, frame_seconds)
    return await asyncio.to_thread(
        detect_faces,
        frame,
        model_pack=biometrics_settings.model_pack,
        provider_preference=biometrics_settings.execution_provider_preference,
        model_cache_dir=model_cache_dir,
    )


def _bbox_distance(
    a: tuple[float, float, float, float], b: tuple[float, float, float, float]
) -> float:
    return max(abs(x - y) for x, y in zip(a, b, strict=True))


def _closest_face(
    detected: Sequence[DetectedFace], bbox: tuple[float, float, float, float]
) -> DetectedFace | None:
    if not detected:
        return None
    closest = min(detected, key=lambda face: _bbox_distance(face.bbox, bbox))
    if _bbox_distance(closest.bbox, bbox) > _BBOX_MATCH_TOLERANCE:
        return None
    return closest


async def enroll_face(
    session: AsyncSession,
    storage: ClipStorage,
    person: Person,
    clip_id: uuid.UUID,
    frame_seconds: float,
    bbox: tuple[float, float, float, float],
    biometrics_settings: BiometricsSettings,
    model_cache_dir: Path,
) -> FaceEmbedding:
    """Re-extracts the frame and re-runs detection rather than trusting a
    client-supplied embedding or cached detection result — the clip file is
    the only source of truth, and raw feature vectors are never something
    to accept from a client."""
    frame = await extract_clip_frame(session, clip_id, frame_seconds)
    detected = await asyncio.to_thread(
        detect_faces,
        frame,
        model_pack=biometrics_settings.model_pack,
        provider_preference=biometrics_settings.execution_provider_preference,
        model_cache_dir=model_cache_dir,
    )
    face = _closest_face(detected, bbox)
    if face is None:
        raise FaceNotFoundError("No detected face matches that selection anymore.")

    embedding_id = uuid.uuid4()
    thumbnail = crop_face_thumbnail(frame, face.bbox)
    thumbnail_path = storage.face_sample_path(person.id, embedding_id)
    await storage.write(thumbnail_path, thumbnail)

    embedding = FaceEmbedding(
        id=embedding_id,
        person_id=person.id,
        embedding=face.embedding,
        source_clip_id=clip_id,
        source_frame_seconds=frame_seconds,
        thumbnail_path=str(thumbnail_path),
    )
    session.add(embedding)

    if not person.thumbnail_path:
        profile_path = storage.person_thumbnail_path(person.id)
        await storage.write(profile_path, thumbnail)
        person.thumbnail_path = str(profile_path)

    await session.commit()
    await session.refresh(embedding)
    return embedding


async def match_faces(
    session: AsyncSession, detected: Sequence[DetectedFace], threshold: float
) -> list[FaceMatch | None]:
    """One result per face in ``detected``, in order. Loads every enrolled
    sample across every person - cheap at household scale, see
    app.biometrics.recognition.best_match."""
    stmt = select(FaceEmbedding.person_id, FaceEmbedding.embedding, FaceEmbedding.is_negative)
    rows = list(await session.execute(stmt))
    positives = [(row.person_id, row.embedding) for row in rows if not row.is_negative]
    negatives = [(row.person_id, row.embedding) for row in rows if row.is_negative]
    return [best_match(face.embedding, positives, negatives, threshold) for face in detected]


REVERTED_LABEL = "Unrecognized person"
"""What a "person" entity's label reverts to when a false-positive report
removes a recognition - distinct from whatever free-text the VLM originally
used (not recoverable - it was overwritten in place), but honest that this
is now deliberately un-attributed rather than a fresh, never-recognized
detection."""


async def report_false_positive(
    session: AsyncSession,
    storage: ClipStorage,
    clip: Clip,
    person: Person,
    biometrics_settings: BiometricsSettings,
    model_cache_dir: Path,
    keyframe_count: int,
) -> bool:
    """A household member is saying ``person`` was recognized in ``clip`` in
    error. Re-detects faces across the clip's keyframes (the original
    per-face match was never persisted - only the aggregate RecognizedFace
    row survives analysis) to find whichever face matched them closely
    enough to have caused it, and stores that face as a negative sample so
    the same face pattern stops matching them in the future (see
    app.biometrics.recognition.best_match) - a report that didn't change
    future matching would be worthless, per design intent.

    Either way, the RecognizedFace record is removed and the clip's current
    analysis has that person's label reverted to generic, since the report
    should be honored even if the exact face can no longer be pinned down
    (e.g. settings changed since the original analysis ran). Returns
    whether a negative sample was actually captured."""
    if clip.storage_path is None:
        raise ClipFrameError("No downloaded clip file to re-examine.")

    stmt = select(FaceEmbedding.embedding).where(
        FaceEmbedding.person_id == person.id, FaceEmbedding.is_negative.is_(False)
    )
    positive_samples = [(person.id, row.embedding) for row in await session.execute(stmt)]

    keyframes = await extract_keyframes(Path(clip.storage_path), keyframe_count)
    best_face: DetectedFace | None = None
    best_frame: bytes | None = None
    best_score = -1.0
    for frame in keyframes:
        faces = await asyncio.to_thread(
            detect_faces,
            frame,
            model_pack=biometrics_settings.model_pack,
            provider_preference=biometrics_settings.execution_provider_preference,
            model_cache_dir=model_cache_dir,
        )
        for face in faces:
            match = best_match(
                face.embedding, positive_samples, [], biometrics_settings.recognition_threshold
            )
            if match is not None and match.score > best_score:
                best_score, best_face, best_frame = match.score, face, frame

    captured = False
    if best_face is not None and best_frame is not None:
        embedding_id = uuid.uuid4()
        thumbnail = crop_face_thumbnail(best_frame, best_face.bbox)
        thumbnail_path = storage.face_sample_path(person.id, embedding_id)
        await storage.write(thumbnail_path, thumbnail)
        session.add(
            FaceEmbedding(
                id=embedding_id,
                person_id=person.id,
                embedding=best_face.embedding,
                is_negative=True,
                source_clip_id=clip.id,
                thumbnail_path=str(thumbnail_path),
            )
        )
        captured = True

    await session.execute(
        delete(RecognizedFace).where(
            RecognizedFace.clip_id == clip.id, RecognizedFace.person_id == person.id
        )
    )
    await _revert_recognized_label(session, clip.id, person.id)
    await session.commit()
    return captured


async def _revert_recognized_label(
    session: AsyncSession, clip_id: uuid.UUID, person_id: uuid.UUID
) -> None:
    stmt = select(Analysis).where(Analysis.clip_id == clip_id, Analysis.is_current.is_(True))
    analysis = (await session.execute(stmt)).scalar_one_or_none()
    if analysis is None:
        return
    person_id_str = str(person_id)
    reverted = [
        {**entity, "label": REVERTED_LABEL, "recognized_person_id": None}
        if entity.get("recognized_person_id") == person_id_str
        else entity
        for entity in analysis.detected_entities
    ]
    if reverted != analysis.detected_entities:
        analysis.detected_entities = reverted
