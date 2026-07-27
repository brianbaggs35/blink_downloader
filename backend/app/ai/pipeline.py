"""Two-tier clip analysis: keyframes -> tier1 VLM call -> optional tier2
escalation -> a persisted Analysis (superseding any prior current one for
the clip), ai_usage rows for every call attempt, and typed Events.

Camera ``security_context`` is wired in here since it's already
homeowner-authored data sitting on the row. Learned ``baseline_context``
and ``feedback_examples`` are accepted as optional parameters but populated
by the feedback/baseline-learning task — the seam is here, the data source
isn't yet.
"""

import asyncio
import io
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import (
    AISettings,
    AIUsage,
    Analysis,
    AnalysisTier,
    Event,
    EventType,
    SuspicionLabel,
)
from app.ai.pricing import estimate_cost_usd
from app.ai.providers import (
    AIProviderError,
    AnalysisRequest,
    AnalysisResult,
    DetectedEntityResult,
    build_provider,
)
from app.biometrics.models import BiometricsSettings, Person, RecognizedFace
from app.biometrics.recognition import (
    DetectedFace,
    FaceMatch,
    ModelLoadError,
    RecognitionError,
    detect_faces,
)
from app.biometrics.service import match_faces
from app.blink.models import Camera, Clip
from app.logs import get_logger
from app.security.crypto import SecretBox
from app.vehicles.geometry import ProximityEstimate, estimate_proximity
from app.vehicles.models import ProximityEvent, Vehicle
from app.video.ffmpeg import extract_keyframes

logger = get_logger(__name__)

SUSPICIOUS_THRESHOLD = 0.6
UNCERTAIN_THRESHOLD = 0.3

_FACE_TO_PERSON_OVERLAP_THRESHOLD = 0.5
"""Fraction of a recognized face's bbox that must fall inside a VLM-detected
"person" entity's bbox before that entity's label is upgraded to the
recognized name. Deliberately not a symmetric IoU: a face is naturally a
small fraction of a whole-body box, so IoU would stay low even for a
correct nested match — this measures containment instead."""

_ENTITY_EVENT_TYPES = {
    "person": EventType.PERSON_DETECTED,
    "vehicle": EventType.VEHICLE_DETECTED,
    "animal": EventType.ANIMAL_DETECTED,
    "package": EventType.PACKAGE_DETECTED,
}


class AnalysisSkippedError(Exception):
    """An expected, non-retryable reason not to analyze a clip right now."""


def suspicion_label_for(score: float) -> SuspicionLabel:
    if score >= SUSPICIOUS_THRESHOLD:
        return SuspicionLabel.SUSPICIOUS
    if score >= UNCERTAIN_THRESHOLD:
        return SuspicionLabel.UNCERTAIN
    return SuspicionLabel.ROUTINE


async def run_analysis(
    session: AsyncSession,
    clip: Clip,
    camera: Camera,
    settings: AISettings,
    encryption_key: str,
    *,
    baseline_context: str | None = None,
    feedback_examples: list[str] | None = None,
    biometrics_settings: BiometricsSettings | None = None,
    biometrics_model_cache_dir: Path | None = None,
) -> Analysis:
    if not clip.storage_path:
        raise AnalysisSkippedError("Clip has not been downloaded yet.")
    if settings.tier1_provider is None or not settings.tier1_model:
        raise AnalysisSkippedError("Tier 1 provider is not configured.")

    keyframes = await extract_keyframes(Path(clip.storage_path), settings.keyframes_per_clip)
    if not keyframes:
        raise AnalysisSkippedError("Could not extract any keyframes from this clip.")

    vehicle = await _get_enabled_vehicle(session, camera.id)
    base_request = AnalysisRequest(
        images=keyframes,
        camera_context=camera.security_context,
        baseline_context=baseline_context,
        feedback_examples=list(feedback_examples or []),
        detect_people_for_proximity=vehicle is not None,
        vehicle_description=vehicle.description if vehicle is not None else None,
    )

    usage_rows: list[AIUsage] = []
    tier1_result, tier1_usage = await _call_tier(
        session, settings, AnalysisTier.TIER1, base_request, clip.id, encryption_key
    )
    usage_rows.append(tier1_usage)
    if tier1_result is None:
        raise AnalysisSkippedError("Tier 1 analysis failed; see ai_usage for the error.")

    final_result, final_tier, escalated = tier1_result, AnalysisTier.TIER1, False
    should_escalate = (
        settings.tier2_enabled
        and tier1_result.suspicion_score >= settings.tier2_suspicion_threshold
    )
    if should_escalate:
        if settings.tier2_provider is None or not settings.tier2_model:
            logger.info("ai.tier2_requested_but_unconfigured", clip_id=str(clip.id))
        else:
            escalation_request = AnalysisRequest(
                images=keyframes,
                camera_context=camera.security_context,
                baseline_context=baseline_context,
                feedback_examples=list(feedback_examples or []),
                detect_people_for_proximity=vehicle is not None,
                vehicle_description=vehicle.description if vehicle is not None else None,
                prior_tier_summary=(
                    f"{tier1_result.summary} "
                    f"(preliminary suspicion: {tier1_result.suspicion_score:.2f})"
                ),
            )
            tier2_result, tier2_usage = await _call_tier(
                session, settings, AnalysisTier.TIER2, escalation_request, clip.id, encryption_key
            )
            usage_rows.append(tier2_usage)
            if tier2_result is not None:
                final_result, final_tier, escalated = tier2_result, AnalysisTier.TIER2, True

    recognized_scores: dict[uuid.UUID, float] = {}
    if (
        biometrics_settings is not None
        and biometrics_model_cache_dir is not None
        and biometrics_settings.enabled
    ):
        try:
            recognized_scores = await _recognize_and_label(
                session,
                keyframes,
                final_result.entities,
                biometrics_settings,
                biometrics_model_cache_dir,
            )
        except (ModelLoadError, RecognitionError) as exc:
            # Biometrics is strictly additive: a model-download hiccup or a
            # bad frame must never throw away a VLM analysis that already
            # succeeded (and was already paid for/rate-limited against).
            # This clip's Analysis is still saved below, just without a
            # recognized-person upgrade for this pass — the next analysis
            # (auto or manual re-analyze) gets another chance.
            logger.warning("biometrics.recognition_skipped", clip_id=str(clip.id), error=str(exc))

    # A trusted household member never trips the label/event/alert just for
    # being recognized - checked here (after recognition, before anything is
    # persisted) rather than by skipping tier2 escalation above: the raw
    # suspicion_score, escalation flag, and any tier2 usage/cost already
    # happened and are recorded as-is, only the final label is overridden.
    bypassed = await _has_bypass_person(session, set(recognized_scores.keys()))
    label = (
        SuspicionLabel.ROUTINE if bypassed else suspicion_label_for(final_result.suspicion_score)
    )
    await _supersede_current_analysis(session, clip.id)

    proximity = None
    if vehicle is not None:
        proximity = _closest_proximity(vehicle, final_result.entities, keyframes[0])

    analysis = Analysis(
        clip_id=clip.id,
        summary=final_result.summary,
        suspicion_score=final_result.suspicion_score,
        suspicion_label=label,
        tier=final_tier,
        escalated=escalated,
        tier1_provider=settings.tier1_provider,
        tier1_model=settings.tier1_model,
        tier2_provider=settings.tier2_provider if escalated else None,
        tier2_model=settings.tier2_model if escalated else None,
        detected_entities=[_entity_to_dict(e) for e in final_result.entities],
        vehicle_proximity=(
            {
                "vehicle_id": str(vehicle.id),
                "distance_feet": proximity.distance_feet,
                "error_margin_feet": proximity.error_margin_feet,
                "breached_threshold": proximity.breached,
            }
            if vehicle is not None and proximity is not None
            else None
        ),
    )
    session.add(analysis)
    await session.flush()

    if vehicle is not None and proximity is not None and proximity.breached:
        await _record_proximity_breach(session, vehicle, clip, analysis.id, proximity)

    if recognized_scores:
        await _upsert_recognized_faces(session, clip.id, analysis.id, recognized_scores)

    # Every ai_usage row for this run (success or failure) is created with
    # analysis_id=None — the Analysis row didn't exist yet, and setting a
    # non-null FK to a not-yet-inserted row would fail. Backfilled now that
    # it does; SQLAlchemy tracks the change and includes it in the same
    # flush/commit below even for rows an earlier failure already committed.
    for usage in usage_rows:
        usage.analysis_id = analysis.id

    await _write_events(session, clip, camera, analysis, final_result, label)
    await session.commit()
    await session.refresh(analysis)
    return analysis


def _entity_to_dict(entity: DetectedEntityResult) -> dict[str, object]:
    return {
        "type": entity.type,
        "label": entity.label,
        "confidence": entity.confidence,
        "bbox": list(entity.bbox) if entity.bbox else None,
        "recognized_person_id": entity.recognized_person_id,
    }


async def _call_tier(
    session: AsyncSession,
    settings: AISettings,
    tier: AnalysisTier,
    request: AnalysisRequest,
    clip_id: uuid.UUID,
    encryption_key: str,
) -> tuple[AnalysisResult | None, AIUsage]:
    """Build the tier's provider, call it, and log an ai_usage row for the
    attempt either way (``analysis_id`` starts unset — the caller backfills
    it once an Analysis row actually exists to point to). The result is
    ``None`` (never raises) for an :class:`AIProviderError` — an expected,
    non-retryable failure the pipeline degrades around; anything else
    propagates."""
    if tier is AnalysisTier.TIER1:
        provider_kind, model = settings.tier1_provider, settings.tier1_model
        encrypted_key, base_url = settings.tier1_encrypted_api_key, settings.tier1_base_url
    else:
        provider_kind, model = settings.tier2_provider, settings.tier2_model
        encrypted_key, base_url = settings.tier2_encrypted_api_key, settings.tier2_base_url
    if provider_kind is None or not model:
        # Both call sites in run_analysis already verify this before
        # invoking _call_tier; a genuine violation is a bug worth a loud
        # failure, not a silently-wrong ai_usage row.
        raise AssertionError(f"{tier.value} provider/model not configured")  # pragma: no cover

    box = SecretBox(encryption_key)
    api_key = box.decrypt(encrypted_key) if encrypted_key else None

    started = time.monotonic()
    try:
        provider = build_provider(provider_kind, model, api_key, base_url)
        result = await provider.analyze(request)
    except AIProviderError as exc:
        usage = AIUsage(
            clip_id=clip_id,
            tier=tier,
            provider=provider_kind,
            model=model,
            frame_count=len(request.images),
            latency_ms=int((time.monotonic() - started) * 1000),
            success=False,
            error_message=str(exc)[:2000],
        )
        session.add(usage)
        # Committed eagerly, not just flushed: a tier1 failure makes
        # run_analysis raise AnalysisSkippedError before it ever reaches its own
        # final commit, and this row must survive that regardless.
        await session.commit()
        logger.warning("ai.tier_call_failed", tier=tier.value, clip_id=str(clip_id), error=str(exc))
        return None, usage

    cost = estimate_cost_usd(provider_kind, model, result.input_tokens, result.output_tokens)
    usage = AIUsage(
        clip_id=clip_id,
        tier=tier,
        provider=provider_kind,
        model=model,
        prompt_tokens=result.input_tokens,
        completion_tokens=result.output_tokens,
        total_tokens=result.input_tokens + result.output_tokens,
        frame_count=len(request.images),
        estimated_cost_usd=cost,
        latency_ms=int((time.monotonic() - started) * 1000),
        success=True,
    )
    session.add(usage)
    await session.flush()
    return result, usage


async def _supersede_current_analysis(session: AsyncSession, clip_id: uuid.UUID) -> None:
    await session.execute(
        update(Analysis)
        .where(Analysis.clip_id == clip_id, Analysis.is_current.is_(True))
        .values(is_current=False, superseded_at=datetime.now(UTC))
    )


async def _write_events(
    session: AsyncSession,
    clip: Clip,
    camera: Camera,
    analysis: Analysis,
    result: AnalysisResult,
    label: SuspicionLabel,
) -> None:
    by_type: dict[EventType, list[DetectedEntityResult]] = {}
    for entity in result.entities:
        event_type = _ENTITY_EVENT_TYPES.get(entity.type, EventType.UNKNOWN_DETECTED)
        by_type.setdefault(event_type, []).append(entity)
    if label is SuspicionLabel.SUSPICIOUS:
        by_type.setdefault(EventType.SUSPICIOUS_ACTIVITY, [])

    for event_type, entities in by_type.items():
        confidence = max((e.confidence for e in entities), default=result.suspicion_score)
        metadata = {"entities": [_entity_to_dict(e) for e in entities]}
        stmt = (
            insert(Event)
            .values(
                clip_id=clip.id,
                analysis_id=analysis.id,
                camera_id=camera.id,
                event_type=event_type,
                confidence=confidence,
                event_metadata=metadata,
                occurred_at=clip.recorded_at,
            )
            .on_conflict_do_update(
                index_elements=[Event.clip_id, Event.event_type],
                set_={
                    "analysis_id": analysis.id,
                    "confidence": confidence,
                    "event_metadata": metadata,
                    "occurred_at": clip.recorded_at,
                },
            )
        )
        await session.execute(stmt)


async def _get_enabled_vehicle(session: AsyncSession, camera_id: uuid.UUID) -> Vehicle | None:
    stmt = select(Vehicle).where(Vehicle.camera_id == camera_id, Vehicle.enabled.is_(True))
    vehicle = (await session.execute(stmt)).scalar_one_or_none()
    if vehicle is not None and len(vehicle.outline_points) < 3:
        return None  # registered but not yet drawn — nothing to measure against
    return vehicle


def _closest_proximity(
    vehicle: Vehicle, entities: list[DetectedEntityResult], reference_keyframe: bytes
) -> ProximityEstimate | None:
    people = [e for e in entities if e.type == "person" and e.bbox is not None]
    if not people:
        return None
    with Image.open(io.BytesIO(reference_keyframe)) as image:
        frame_width, frame_height = image.size

    estimates = (
        estimate_proximity(
            vehicle_outline=[(x, y) for x, y in vehicle.outline_points],
            vehicle_length_feet=vehicle.estimated_length_feet,
            distance_threshold_feet=vehicle.distance_threshold_feet,
            person_bbox=person.bbox,  # type: ignore[arg-type]
            frame_width=frame_width,
            frame_height=frame_height,
        )
        for person in people
    )
    valid = [e for e in estimates if e is not None]
    if not valid:
        return None
    return min(valid, key=lambda e: e.distance_feet)


async def _record_proximity_breach(
    session: AsyncSession,
    vehicle: Vehicle,
    clip: Clip,
    analysis_id: uuid.UUID,
    proximity: ProximityEstimate,
) -> None:
    session.add(
        ProximityEvent(
            vehicle_id=vehicle.id,
            clip_id=clip.id,
            distance_feet=proximity.distance_feet,
            error_margin_feet=proximity.error_margin_feet,
            occurred_at=clip.recorded_at,
        )
    )
    metadata = {
        "distance_feet": proximity.distance_feet,
        "error_margin_feet": proximity.error_margin_feet,
        "vehicle_id": str(vehicle.id),
    }
    stmt = (
        insert(Event)
        .values(
            clip_id=clip.id,
            analysis_id=analysis_id,
            camera_id=vehicle.camera_id,
            event_type=EventType.VEHICLE_PROXIMITY_BREACH,
            confidence=1.0,
            event_metadata=metadata,
            occurred_at=clip.recorded_at,
        )
        .on_conflict_do_update(
            index_elements=[Event.clip_id, Event.event_type],
            set_={
                "analysis_id": analysis_id,
                "event_metadata": metadata,
                "occurred_at": clip.recorded_at,
            },
        )
    )
    await session.execute(stmt)


async def _recognize_and_label(
    session: AsyncSession,
    keyframes: list[bytes],
    entities: list[DetectedEntityResult],
    biometrics_settings: BiometricsSettings,
    model_cache_dir: Path,
) -> dict[uuid.UUID, float]:
    """Runs local face detection + matching against every keyframe and, for
    any match found in the first keyframe, upgrades the corresponding
    "person" entity's generic label to the recognized name in place
    (entities from keyframes[0] onward is the same frame _closest_proximity
    already interprets bboxes against).

    Never sends a face image, embedding, or name to the VLM - the VLM call
    already happened before this runs, on the same generic keyframes as
    always. Returns the best match score per recognized person, for the
    caller to persist as RecognizedFace rows once an Analysis row exists.
    """
    best_score: dict[uuid.UUID, float] = {}
    first_frame_matches: list[tuple[DetectedFace, FaceMatch]] = []

    for index, frame in enumerate(keyframes):
        faces = await asyncio.to_thread(
            detect_faces,
            frame,
            model_pack=biometrics_settings.model_pack,
            provider_preference=biometrics_settings.execution_provider_preference,
            model_cache_dir=model_cache_dir,
        )
        if not faces:
            continue
        matches = await match_faces(session, faces, biometrics_settings.recognition_threshold)
        for face, match in zip(faces, matches, strict=True):
            if match is None:
                continue
            if index == 0:
                first_frame_matches.append((face, match))
            if match.person_id not in best_score or match.score > best_score[match.person_id]:
                best_score[match.person_id] = match.score

    if first_frame_matches:
        names = await _person_names(session, {match.person_id for _, match in first_frame_matches})
        _upgrade_person_labels(entities, first_frame_matches, names)

    return best_score


async def _person_names(session: AsyncSession, person_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    stmt = select(Person.id, Person.name).where(Person.id.in_(person_ids))
    return {row.id: row.name for row in await session.execute(stmt)}


async def _has_bypass_person(session: AsyncSession, person_ids: set[uuid.UUID]) -> bool:
    """True if any recognized person in this clip is flagged
    never_mark_suspicious."""
    if not person_ids:
        return False
    stmt = (
        select(Person.id)
        .where(Person.id.in_(person_ids), Person.never_mark_suspicious.is_(True))
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


def _bbox_overlap_ratio(
    face_bbox: tuple[float, float, float, float], person_bbox: tuple[float, float, float, float]
) -> float:
    """What fraction of ``face_bbox`` falls inside ``person_bbox``. 1.0
    means fully contained; see _FACE_TO_PERSON_OVERLAP_THRESHOLD for why
    this isn't a symmetric IoU."""
    fx, fy, fw, fh = face_bbox
    px, py, pw, ph = person_bbox
    ix1, iy1 = max(fx, px), max(fy, py)
    ix2, iy2 = min(fx + fw, px + pw), min(fy + fh, py + ph)
    intersection = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    face_area = fw * fh
    if face_area <= 0:
        return 0.0
    return intersection / face_area


def _upgrade_person_labels(
    entities: list[DetectedEntityResult],
    face_matches: list[tuple[DetectedFace, FaceMatch]],
    names_by_person_id: dict[uuid.UUID, str],
) -> None:
    person_entities = [e for e in entities if e.type == "person" and e.bbox is not None]
    if not person_entities:
        return
    for face, match in face_matches:
        name = names_by_person_id.get(match.person_id)
        if name is None:
            continue
        overlaps = [
            (entity, _bbox_overlap_ratio(face.bbox, entity.bbox))  # type: ignore[arg-type]
            for entity in person_entities
        ]
        best_entity, best_overlap = max(overlaps, key=lambda pair: pair[1])
        if best_overlap >= _FACE_TO_PERSON_OVERLAP_THRESHOLD:
            best_entity.label = name
            best_entity.recognized_person_id = str(match.person_id)


async def _upsert_recognized_faces(
    session: AsyncSession,
    clip_id: uuid.UUID,
    analysis_id: uuid.UUID,
    best_score: dict[uuid.UUID, float],
) -> None:
    for person_id, score in best_score.items():
        stmt = (
            insert(RecognizedFace)
            .values(
                clip_id=clip_id,
                analysis_id=analysis_id,
                person_id=person_id,
                confidence=score,
            )
            .on_conflict_do_update(
                index_elements=[RecognizedFace.clip_id, RecognizedFace.person_id],
                set_={"analysis_id": analysis_id, "confidence": score},
            )
        )
        await session.execute(stmt)
