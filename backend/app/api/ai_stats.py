"""Aggregate stats behind the AI and AI Usage tabs — viewer-accessible,
matching the rest of the AI/clips surface (this is "viewing", not managing).
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AIUsage, Analysis, Feedback, FeedbackVerdict, SuspicionLabel
from app.ai.stats_schemas import (
    AiStatsResponse,
    AiUsageDailyPoint,
    AiUsageProviderBreakdown,
    AiUsageResponse,
)
from app.db import get_session
from app.users.auth import current_active_user
from app.vehicles.models import ProximityEvent

router = APIRouter(prefix="/ai", tags=["ai-stats"])

USAGE_HISTORY_DAYS = 30


@router.get("/stats", response_model=AiStatsResponse)
async def get_ai_stats(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_active_user)],
) -> AiStatsResponse:
    current = Analysis.is_current.is_(True)

    label_rows = await session.execute(
        select(Analysis.suspicion_label, func.count())
        .where(current)
        .group_by(Analysis.suspicion_label)
    )
    # dict(label_rows) resolves pyright to an unrelated dict() overload for
    # a Sequence[Row[...]] input (a known Row-typing friction point) — the
    # comprehension is the one that actually type-checks.
    label_counts = {label: count for label, count in label_rows}  # noqa: C416
    total_analyzed = sum(label_counts.values())

    escalated_count = (
        await session.execute(
            select(func.count()).select_from(Analysis).where(current, Analysis.escalated.is_(True))
        )
    ).scalar_one()

    since = datetime.now(UTC) - timedelta(days=7)
    analyzed_recent = (
        await session.execute(
            select(func.count()).select_from(Analysis).where(current, Analysis.created_at >= since)
        )
    ).scalar_one()

    breaches = (
        await session.execute(select(func.count()).select_from(ProximityEvent))
    ).scalar_one()

    feedback_rows = await session.execute(
        select(Feedback.verdict, func.count()).group_by(Feedback.verdict)
    )
    feedback_counts = {verdict: count for verdict, count in feedback_rows}  # noqa: C416
    total_feedback = sum(feedback_counts.values())

    return AiStatsResponse(
        total_analyzed=total_analyzed,
        suspicious_count=label_counts.get(SuspicionLabel.SUSPICIOUS, 0),
        uncertain_count=label_counts.get(SuspicionLabel.UNCERTAIN, 0),
        routine_count=label_counts.get(SuspicionLabel.ROUTINE, 0),
        escalated_count=escalated_count,
        analyzed_last_7_days=analyzed_recent,
        vehicle_proximity_breaches=breaches,
        total_feedback=total_feedback,
        correct_feedback=feedback_counts.get(FeedbackVerdict.CORRECT, 0),
        false_positive_feedback=feedback_counts.get(FeedbackVerdict.FALSE_POSITIVE, 0),
        false_negative_feedback=feedback_counts.get(FeedbackVerdict.FALSE_NEGATIVE, 0),
    )


@router.get("/usage", response_model=AiUsageResponse)
async def get_ai_usage(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_active_user)],
) -> AiUsageResponse:
    total_tokens, total_cost_usd, total_calls = (
        await session.execute(
            select(
                func.coalesce(func.sum(AIUsage.total_tokens), 0),
                func.coalesce(func.sum(AIUsage.estimated_cost_usd), 0),
                func.count(),
            )
        )
    ).one()

    failed_calls = (
        await session.execute(
            select(func.count()).select_from(AIUsage).where(AIUsage.success.is_(False))
        )
    ).scalar_one()

    since = datetime.now(UTC) - timedelta(days=USAGE_HISTORY_DAYS)
    daily_rows = (
        await session.execute(
            select(
                func.date(AIUsage.created_at),
                func.coalesce(func.sum(AIUsage.total_tokens), 0),
                func.coalesce(func.sum(AIUsage.estimated_cost_usd), 0),
                func.count(),
            )
            .where(AIUsage.created_at >= since)
            .group_by(func.date(AIUsage.created_at))
            .order_by(func.date(AIUsage.created_at))
        )
    ).all()
    daily = [
        AiUsageDailyPoint(date=str(day), tokens=tokens, cost_usd=float(cost), calls=calls)
        for day, tokens, cost, calls in daily_rows
    ]

    provider_rows = (
        await session.execute(
            select(
                AIUsage.provider,
                AIUsage.model,
                func.coalesce(func.sum(AIUsage.total_tokens), 0),
                func.coalesce(func.sum(AIUsage.estimated_cost_usd), 0),
                func.count(),
            ).group_by(AIUsage.provider, AIUsage.model)
        )
    ).all()
    by_provider = [
        AiUsageProviderBreakdown(
            provider=provider.value, model=model, tokens=tokens, cost_usd=float(cost), calls=calls
        )
        for provider, model, tokens, cost, calls in provider_rows
    ]

    return AiUsageResponse(
        total_tokens=total_tokens,
        total_cost_usd=float(total_cost_usd),
        total_calls=total_calls,
        failed_calls=failed_calls,
        daily=daily,
        by_provider=by_provider,
    )
