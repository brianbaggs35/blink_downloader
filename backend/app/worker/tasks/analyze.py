"""Per-clip AI analysis: tier1 (+ optional tier2 escalation), triggered
automatically after a successful download, or on demand via reanalyze /
bulk-analyze. AnalysisSkippedError (expected, non-retryable reasons — AI
disabled, no provider configured, no keyframes) is caught here and turned
into a status string rather than propagated for arq to retry.
"""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.pipeline import AnalysisSkippedError, run_analysis
from app.ai.service import get_ai_settings
from app.blink.models import Camera, Clip
from app.config import get_settings
from app.logs import get_logger

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

        try:
            analysis = await run_analysis(
                session, clip, camera, ai_settings, settings.encryption_key
            )
        except AnalysisSkippedError as exc:
            logger.info("ai.analyze_skipped", clip_id=clip_id, reason=str(exc))
            return "skipped"

        logger.info(
            "ai.analyze_completed",
            clip_id=clip_id,
            suspicion=analysis.suspicion_score,
            escalated=analysis.escalated,
        )
        return "ok"
