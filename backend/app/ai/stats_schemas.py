"""Pydantic schemas for the AI/AI Usage tabs' aggregate stats endpoints."""

from pydantic import BaseModel


class AiStatsResponse(BaseModel):
    total_analyzed: int
    suspicious_count: int
    uncertain_count: int
    routine_count: int
    escalated_count: int
    analyzed_last_7_days: int
    vehicle_proximity_breaches: int
    total_feedback: int
    correct_feedback: int
    false_positive_feedback: int
    false_negative_feedback: int


class AiUsageDailyPoint(BaseModel):
    date: str
    tokens: int
    cost_usd: float
    calls: int


class AiUsageProviderBreakdown(BaseModel):
    provider: str
    model: str
    tokens: int
    cost_usd: float
    calls: int


class AiUsageResponse(BaseModel):
    total_tokens: int
    total_cost_usd: float
    total_calls: int
    failed_calls: int
    total_frames_analyzed: int
    frames_analyzed_today: int
    daily: list[AiUsageDailyPoint]
    by_provider: list[AiUsageProviderBreakdown]
