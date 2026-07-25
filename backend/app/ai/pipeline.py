"""Two-tier clip analysis: keyframes -> tier1 VLM call -> optional tier2
escalation -> a persisted Analysis (superseding any prior current one for
the clip), ai_usage rows for every call attempt, and typed Events.

Camera ``security_context`` is wired in here since it's already
homeowner-authored data sitting on the row. Learned ``baseline_context``
and ``feedback_examples`` are accepted as optional parameters but populated
by the feedback/baseline-learning task — the seam is here, the data source
isn't yet.
"""

import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import update
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
from app.blink.models import Camera, Clip
from app.logs import get_logger
from app.security.crypto import SecretBox
from app.video.ffmpeg import extract_keyframes

logger = get_logger(__name__)

SUSPICIOUS_THRESHOLD = 0.6
UNCERTAIN_THRESHOLD = 0.3

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
) -> Analysis:
    if not clip.storage_path:
        raise AnalysisSkippedError("Clip has not been downloaded yet.")
    if settings.tier1_provider is None or not settings.tier1_model:
        raise AnalysisSkippedError("Tier 1 provider is not configured.")

    keyframes = await extract_keyframes(Path(clip.storage_path), settings.keyframes_per_clip)
    if not keyframes:
        raise AnalysisSkippedError("Could not extract any keyframes from this clip.")

    base_request = AnalysisRequest(
        images=keyframes,
        camera_context=camera.security_context,
        baseline_context=baseline_context,
        feedback_examples=list(feedback_examples or []),
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

    label = suspicion_label_for(final_result.suspicion_score)
    await _supersede_current_analysis(session, clip.id)

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
    )
    session.add(analysis)
    await session.flush()

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
