"""Feedback-driven learning: camera baselines (passive, from every
analysis) and few-shot prompt conditioning (from corrections specifically)
— two of the three reinforcing loops in docs/ARCHITECTURE.md.

The third (pgvector exemplar retrieval) is deliberately not built here: at
a single household's realistic feedback volume (dozens to low hundreds of
corrections, not millions), k-NN over an embedding index is real
infrastructure — another model to bundle, a new index to maintain — for
marginal benefit over "the household's most recent corrections for this
camera," which already gives the VLM concrete, relevant examples to weigh.

Baseline updates use a plain read-modify-write on the JSONB histogram, not
row locking or a compare-and-swap loop: it's an approximate rolling
statistic by design (a hint of what's normal, not an audit ledger), so an
occasional lost increment under concurrent same-camera analysis is an
acceptable, deliberate trade against the complexity of making it exact.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import Analysis, CameraBaseline, Feedback, FeedbackVerdict
from app.blink.models import Clip

FALSE_POSITIVE_BASELINE_WEIGHT = 3
"""A false-positive correction ("this routine thing was wrongly flagged")
counts several times as much as one passive observation, so the baseline
accepts that pattern faster than waiting for it to naturally recur."""

MAX_BASELINE_DIGEST_ENTITIES = 5


async def _get_or_create_baseline(session: AsyncSession, camera_id: uuid.UUID) -> CameraBaseline:
    stmt = (
        insert(CameraBaseline)
        .values(camera_id=camera_id)
        .on_conflict_do_nothing(index_elements=[CameraBaseline.camera_id])
        .returning(CameraBaseline)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is not None:
        return row
    return (
        await session.execute(select(CameraBaseline).where(CameraBaseline.camera_id == camera_id))
    ).scalar_one()


def _bump_hour(
    counts: dict[str, dict[str, int]], hour: str, entity_types: set[str], weight: int
) -> None:
    hour_counts = dict(counts.get(hour, {}))
    for entity_type in entity_types:
        hour_counts[entity_type] = hour_counts.get(entity_type, 0) + weight
    counts[hour] = hour_counts


async def update_baseline(
    session: AsyncSession, camera_id: uuid.UUID, recorded_at: datetime, entity_types: list[str]
) -> None:
    """Called after every analysis, suspicious or not — this is the passive
    "what does this camera normally see" accumulation."""
    if not entity_types:
        return
    row = await _get_or_create_baseline(session, camera_id)
    counts = dict(row.hourly_entity_counts)
    _bump_hour(counts, str(recorded_at.hour), set(entity_types), weight=1)
    row.hourly_entity_counts = counts
    row.total_observations += 1


async def reinforce_baseline_from_feedback(
    session: AsyncSession, camera_id: uuid.UUID, recorded_at: datetime, entity_types: list[str]
) -> None:
    """Called when a false-positive correction confirms a pattern is
    routine — an extra push beyond the single passive observation it
    already contributed, so the household's correction visibly moves the
    baseline rather than waiting to be outweighed by future recurrences."""
    if not entity_types:
        return
    row = await _get_or_create_baseline(session, camera_id)
    counts = dict(row.hourly_entity_counts)
    weight = FALSE_POSITIVE_BASELINE_WEIGHT
    _bump_hour(counts, str(recorded_at.hour), set(entity_types), weight=weight)
    row.hourly_entity_counts = counts


async def baseline_context_for(
    session: AsyncSession, camera_id: uuid.UUID, hour: int
) -> str | None:
    """A short text digest of what this camera normally sees around this
    hour, for the VLM prompt — or None if there's not yet any history."""
    row = (
        await session.execute(select(CameraBaseline).where(CameraBaseline.camera_id == camera_id))
    ).scalar_one_or_none()
    if row is None:
        return None
    hour_counts = row.hourly_entity_counts.get(str(hour), {})
    if not hour_counts:
        return None
    top = sorted(hour_counts.items(), key=lambda item: item[1], reverse=True)
    top = top[:MAX_BASELINE_DIGEST_ENTITIES]
    parts = ", ".join(f"{entity_type} ({count}x)" for entity_type, count in top)
    return f"Around this time of day, this camera typically sees: {parts}."


async def feedback_examples_for(
    session: AsyncSession, camera_id: uuid.UUID, limit: int
) -> list[str]:
    """The household's most recent corrections for this camera, as short
    few-shot text for the VLM prompt. Only corrections (false positive/
    negative) are included — a confirmed-correct call has nothing to teach
    the model that it isn't already doing."""
    if limit <= 0:
        return []
    stmt = (
        select(Feedback, Analysis)
        .join(Analysis, Feedback.analysis_id == Analysis.id)
        .join(Clip, Analysis.clip_id == Clip.id)
        .where(
            Clip.camera_id == camera_id,
            Feedback.verdict.in_([FeedbackVerdict.FALSE_POSITIVE, FeedbackVerdict.FALSE_NEGATIVE]),
        )
        .order_by(Feedback.created_at.desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    examples: list[str] = []
    for feedback, analysis in rows:
        if feedback.verdict == FeedbackVerdict.FALSE_POSITIVE:
            examples.append(f"Flagged suspicious, but was actually routine: {analysis.summary}")
        else:
            examples.append(
                f"Not flagged, but should have been considered suspicious: {analysis.summary}"
            )
    return examples


async def record_feedback(
    session: AsyncSession,
    analysis: Analysis,
    clip: Clip,
    user_id: uuid.UUID,
    verdict: FeedbackVerdict,
    note: str | None,
) -> Feedback:
    feedback = Feedback(
        analysis_id=analysis.id, user_id=user_id, verdict=verdict, note=note, applied=True
    )
    session.add(feedback)
    if verdict == FeedbackVerdict.FALSE_POSITIVE:
        entity_types = [str(e.get("type", "unknown")) for e in analysis.detected_entities]
        await reinforce_baseline_from_feedback(
            session, clip.camera_id, clip.recorded_at, entity_types
        )
    await session.commit()
    await session.refresh(feedback)
    return feedback
