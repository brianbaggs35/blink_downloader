"""Per-clip AI analysis: tier1 (+ optional tier2 escalation), triggered
automatically after a successful download, or on demand via reanalyze /
bulk-analyze. AnalysisSkippedError (expected, non-retryable reasons — AI
disabled, no provider configured, no keyframes) is caught here and turned
into a status string rather than propagated for arq to retry.
"""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.learning import baseline_context_for, feedback_examples_for, update_baseline
from app.ai.models import Analysis, SuspicionLabel
from app.ai.pipeline import AnalysisSkippedError, run_analysis
from app.ai.service import get_ai_settings
from app.alerts.models import AlertSettings
from app.alerts.service import get_alert_settings
from app.blink.models import Camera, Clip
from app.config import get_settings
from app.logs import get_logger
from app.worker.tasks.alerts import SEND_ALERT_JOB_NAME

logger = get_logger(__name__)

ANALYZE_JOB_NAME = "analyze_clip"


async def analyze_clip(ctx: dict[Any, Any], clip_id: str) -> str:
    settings = get_settings()
    sessionmaker: async_sessionmaker[AsyncSession] = ctx["sessionmaker"]
    async with sessionmaker() as session:
        clip = await session.get(Clip, UUID(clip_id))
        if clip is None:
            logger.info("ai.analyze_skipped_missing_clip", clip_id=clip_id)
            return "clip_not_found"

        ai_settings = await get_ai_settings(session)
        if not ai_settings.enabled:
            return "ai_disabled"

        camera = await session.get(Camera, clip.camera_id)
        if camera is None:  # pragma: no cover — FK guarantees this can't happen
            return "camera_missing"

        baseline_context = await baseline_context_for(session, camera.id, clip.recorded_at.hour)
        feedback_examples = await feedback_examples_for(
            session, camera.id, ai_settings.feedback_context_count
        )
        try:
            analysis = await run_analysis(
                session,
                clip,
                camera,
                ai_settings,
                settings.encryption_key,
                baseline_context=baseline_context,
                feedback_examples=feedback_examples,
            )
        except AnalysisSkippedError as exc:
            logger.info("ai.analyze_skipped", clip_id=clip_id, reason=str(exc))
            return "skipped"

        entity_types = [str(e.get("type", "unknown")) for e in analysis.detected_entities]
        await update_baseline(session, camera.id, clip.recorded_at, entity_types)
        await session.commit()

        alert_settings = await get_alert_settings(session)
        await _maybe_send_alerts(ctx, alert_settings, camera, analysis)

        logger.info(
            "ai.analyze_completed",
            clip_id=clip_id,
            suspicion=analysis.suspicion_score,
            escalated=analysis.escalated,
        )
        return "ok"


async def _maybe_send_alerts(
    ctx: dict[Any, Any], alert_settings: AlertSettings, camera: Camera, analysis: Analysis
) -> None:
    if (
        alert_settings.alert_on_suspicious_clip
        and analysis.suspicion_label == SuspicionLabel.SUSPICIOUS
        and analysis.suspicion_score >= alert_settings.suspicion_alert_threshold
    ):
        message = (
            f"[{camera.name}] Suspicious activity (score {analysis.suspicion_score:.2f}): "
            f"{analysis.summary}"
        )
        await ctx["redis"].enqueue_job(
            SEND_ALERT_JOB_NAME,
            camera_id=str(camera.id),
            reason="suspicious_activity",
            message=message,
        )

    proximity = analysis.vehicle_proximity
    if alert_settings.alert_on_vehicle_proximity and proximity and proximity["breached_threshold"]:
        message = (
            f"[{camera.name}] Someone is ~{proximity['distance_feet']}ft "
            f"(±{proximity['error_margin_feet']}ft) from your vehicle: {analysis.summary}"
        )
        await ctx["redis"].enqueue_job(
            SEND_ALERT_JOB_NAME,
            camera_id=str(camera.id),
            reason="vehicle_proximity",
            message=message,
        )
