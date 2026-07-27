"""Local facial recognition: settings, enrolled people, and clip-frame
enrollment.

Viewing people/thumbnails and previewing detected faces is available to any
signed-in household member (matching the rest of the AI/clips surface);
everything that creates, renames, deletes, or enrolls is admin-only.
"""

import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.service import get_ai_settings
from app.biometrics.models import BiometricsSettings, FaceEmbedding, Person
from app.biometrics.recognition import ModelLoadError, RecognitionError, available_providers
from app.biometrics.schemas import (
    BiometricsSettingsRead,
    BiometricsSettingsUpdate,
    DetectedFaceRead,
    EnrollFaceRequest,
    FaceEmbeddingRead,
    PersonCreate,
    PersonRead,
    PersonUpdate,
    ReportFalsePositiveRead,
    VerifyModelRead,
)
from app.biometrics.service import (
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
    report_false_positive,
    update_biometrics_settings,
    update_person,
    verify_model,
)
from app.blink.models import Clip
from app.config import get_settings
from app.db import get_session
from app.settings.service import resolve_storage_dir
from app.storage.service import ClipStorage, get_clip_storage
from app.users.auth import current_active_user, current_superuser

router = APIRouter(prefix="/biometrics", tags=["biometrics"])


async def _storage(session: AsyncSession) -> ClipStorage:
    return get_clip_storage(await resolve_storage_dir(session, get_settings()))


def _person_read(person: Person) -> PersonRead:
    return PersonRead(
        id=person.id,
        name=person.name,
        never_mark_suspicious=person.never_mark_suspicious,
        has_thumbnail=bool(person.thumbnail_path and Path(person.thumbnail_path).exists()),
        face_count=len(person.face_embeddings),
        created_at=person.created_at,
        updated_at=person.updated_at,
    )


def _settings_read(row: BiometricsSettings) -> BiometricsSettingsRead:
    return BiometricsSettingsRead(
        enabled=row.enabled,
        model_pack=row.model_pack,
        execution_provider_preference=row.execution_provider_preference,
        recognition_threshold=row.recognition_threshold,
        available_providers=available_providers(),
        updated_at=row.updated_at,
    )


async def _get_person_or_404(session: AsyncSession, person_id: uuid.UUID) -> Person:
    person = await get_person(session, person_id)
    if person is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Person not found.")
    return person


async def _get_clip_or_404(session: AsyncSession, clip_id: uuid.UUID) -> Clip:
    clip = await session.get(Clip, clip_id)
    if clip is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clip not found.")
    return clip


def _get_face_or_404(person: Person, face_id: uuid.UUID) -> FaceEmbedding:
    for face in person.face_embeddings:
        if face.id == face_id:
            return face
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="Face sample not found for this person."
    )


def _file_or_404(path_str: str | None, what: str) -> Path:
    if not path_str or not Path(path_str).exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No {what} yet.")
    return Path(path_str)


@router.get("/settings", response_model=BiometricsSettingsRead)
async def get_settings_route(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> BiometricsSettingsRead:
    return _settings_read(await get_biometrics_settings(session))


@router.put("/settings", response_model=BiometricsSettingsRead)
async def update_settings_route(
    payload: BiometricsSettingsUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> BiometricsSettingsRead:
    row = await update_biometrics_settings(session, payload)
    return _settings_read(row)


@router.post("/settings/verify-model", response_model=VerifyModelRead)
async def verify_model_route(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> VerifyModelRead:
    """Downloads/loads the currently-configured model pack right now and
    reports pass/fail, so enabling biometrics in Settings gives an admin
    immediate feedback instead of a silent first-analysis surprise."""
    biometrics_settings = await get_biometrics_settings(session)
    try:
        providers = await verify_model(
            biometrics_settings, get_settings().biometrics_model_cache_dir
        )
    except ModelLoadError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return VerifyModelRead(model_pack=biometrics_settings.model_pack, providers=providers)


@router.get("/people", response_model=list[PersonRead])
async def list_people_route(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_active_user)],
) -> list[PersonRead]:
    people = await list_people(session)
    return [_person_read(p) for p in people]


@router.post("/people", response_model=PersonRead, status_code=status.HTTP_201_CREATED)
async def create_person_route(
    payload: PersonCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> PersonRead:
    person = await create_person(session, payload.name)
    return _person_read(person)


@router.get("/people/{person_id}", response_model=PersonRead)
async def get_person_route(
    person_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_active_user)],
) -> PersonRead:
    return _person_read(await _get_person_or_404(session, person_id))


@router.put("/people/{person_id}", response_model=PersonRead)
async def update_person_route(
    person_id: uuid.UUID,
    payload: PersonUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> PersonRead:
    person = await _get_person_or_404(session, person_id)
    person = await update_person(session, person, payload)
    return _person_read(person)


@router.delete("/people/{person_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_person_route(
    person_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> None:
    person = await _get_person_or_404(session, person_id)
    await delete_person(session, person, await _storage(session))


@router.get("/people/{person_id}/thumbnail")
async def person_thumbnail_route(
    person_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_active_user)],
) -> FileResponse:
    person = await _get_person_or_404(session, person_id)
    path = _file_or_404(person.thumbnail_path, "thumbnail")
    return FileResponse(path, media_type="image/jpeg", content_disposition_type="inline")


@router.get("/people/{person_id}/faces", response_model=list[FaceEmbeddingRead])
async def list_person_faces_route(
    person_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_active_user)],
) -> list[FaceEmbedding]:
    person = await _get_person_or_404(session, person_id)
    return sorted(person.face_embeddings, key=lambda f: f.created_at, reverse=True)


@router.get("/people/{person_id}/faces/{face_id}/thumbnail")
async def face_thumbnail_route(
    person_id: uuid.UUID,
    face_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_active_user)],
) -> FileResponse:
    person = await _get_person_or_404(session, person_id)
    face = _get_face_or_404(person, face_id)
    path = _file_or_404(face.thumbnail_path, "face sample")
    return FileResponse(path, media_type="image/jpeg", content_disposition_type="inline")


@router.delete("/people/{person_id}/faces/{face_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_face_route(
    person_id: uuid.UUID,
    face_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> None:
    person = await _get_person_or_404(session, person_id)
    face = _get_face_or_404(person, face_id)
    storage = await _storage(session)
    await storage.delete(storage.face_sample_path(person_id, face_id))
    await session.delete(face)
    await session.commit()


@router.get("/clips/{clip_id}/frame")
async def clip_frame_route(
    clip_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_active_user)],
    frame_seconds: Annotated[float, Query(ge=0)],
) -> Response:
    try:
        frame = await extract_clip_frame(session, clip_id, frame_seconds)
    except ClipFrameError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return Response(content=frame, media_type="image/jpeg")


@router.get("/clips/{clip_id}/detect-faces", response_model=list[DetectedFaceRead])
async def detect_faces_route(
    clip_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_active_user)],
    frame_seconds: Annotated[float, Query(ge=0)],
) -> list[DetectedFaceRead]:
    biometrics_settings = await get_biometrics_settings(session)
    try:
        faces = await detect_faces_in_clip_frame(
            session,
            clip_id,
            frame_seconds,
            biometrics_settings,
            get_settings().biometrics_model_cache_dir,
        )
    except ClipFrameError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return [DetectedFaceRead(bbox=f.bbox, confidence=f.confidence) for f in faces]


@router.post("/people/{person_id}/enroll", response_model=FaceEmbeddingRead)
async def enroll_face_route(
    person_id: uuid.UUID,
    payload: EnrollFaceRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> FaceEmbedding:
    person = await _get_person_or_404(session, person_id)
    biometrics_settings = await get_biometrics_settings(session)
    try:
        return await enroll_face(
            session,
            await _storage(session),
            person,
            payload.clip_id,
            payload.frame_seconds,
            payload.bbox,
            biometrics_settings,
            get_settings().biometrics_model_cache_dir,
        )
    except ClipFrameError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except FaceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/clips/{clip_id}/people/{person_id}/report-false-positive",
    response_model=ReportFalsePositiveRead,
)
async def report_false_positive_route(
    clip_id: uuid.UUID,
    person_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> ReportFalsePositiveRead:
    """ "This wasn't {name}" from the clip modal — see
    app.biometrics.service.report_false_positive for what this actually
    does to future matching, not just this one clip."""
    clip = await _get_clip_or_404(session, clip_id)
    person = await _get_person_or_404(session, person_id)
    biometrics_settings = await get_biometrics_settings(session)
    ai_settings = await get_ai_settings(session)
    try:
        captured = await report_false_positive(
            session,
            await _storage(session),
            clip,
            person,
            biometrics_settings,
            get_settings().biometrics_model_cache_dir,
            ai_settings.keyframes_per_clip,
        )
    except ClipFrameError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (ModelLoadError, RecognitionError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return ReportFalsePositiveRead(negative_sample_captured=captured)
