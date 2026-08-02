"""Pydantic schemas for the AI settings and analysis API surface."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.ai.models import AIProviderKind, AnalysisTier, FeedbackVerdict, SuspicionLabel


class AISettingsRead(BaseModel):
    enabled: bool
    tier1_provider: AIProviderKind | None
    tier1_model: str | None
    tier1_api_key_set: bool
    tier1_base_url: str | None
    tier2_enabled: bool
    tier2_provider: AIProviderKind | None
    tier2_model: str | None
    tier2_api_key_set: bool
    tier2_base_url: str | None
    tier2_linked_to_tier1: bool
    keyframes_per_clip: int
    tier2_suspicion_threshold: float
    feedback_context_count: int


class AISettingsUpdate(BaseModel):
    enabled: bool
    tier1_provider: AIProviderKind | None = None
    tier1_model: str | None = None
    tier1_api_key: str | None = None
    """None leaves the stored key untouched; "" clears it; anything else replaces it."""
    tier1_base_url: str | None = None

    tier2_enabled: bool = True
    tier2_provider: AIProviderKind | None = None
    tier2_model: str | None = None
    tier2_api_key: str | None = None
    tier2_base_url: str | None = None
    tier2_linked_to_tier1: bool = False
    """When true, tier2_provider/tier2_api_key/tier2_base_url are ignored and
    tier1's resolved values are copied onto tier2 instead - see
    app.ai.service.update_ai_settings."""

    keyframes_per_clip: int = Field(default=4, ge=1, le=12)
    tier2_suspicion_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    feedback_context_count: int = Field(default=5, ge=0, le=20)


class AIConnectionTestRequest(BaseModel):
    tier: Literal["tier1", "tier2"]
    provider: AIProviderKind
    model: str = Field(min_length=1)
    api_key: str | None = None
    """Omit to test with the already-saved key for this tier, if any."""
    base_url: str | None = None


class AIConnectionTestResponse(BaseModel):
    ok: bool
    detail: str | None = None


class AIModelListRequest(BaseModel):
    tier: Literal["tier1", "tier2"]
    provider: AIProviderKind
    api_key: str | None = None
    """Omit to fetch with the already-saved key for this tier, if any."""
    base_url: str | None = None


class AIModelListResponse(BaseModel):
    ok: bool
    detail: str | None = None
    models: list[str] = Field(default_factory=list)


class DetectedEntityRead(BaseModel):
    type: str
    label: str
    confidence: float
    bbox: list[float] | None
    recognized_person_id: str | None = None
    """Set only when label was locally upgraded from generic to an enrolled
    person's name (see app.ai.pipeline._upgrade_person_labels) — lets the
    frontend distinguish a real recognized name from the VLM's own
    generic/descriptive label text."""

    model_config = {"from_attributes": True}


class AnalysisRead(BaseModel):
    id: uuid.UUID
    clip_id: uuid.UUID
    summary: str
    suspicion_score: float
    suspicion_label: SuspicionLabel
    tier: AnalysisTier
    escalated: bool
    tier1_provider: AIProviderKind | None
    tier1_model: str | None
    tier2_provider: AIProviderKind | None
    tier2_model: str | None
    detected_entities: list[DetectedEntityRead]
    vehicle_proximity: dict[str, Any] | None
    created_at: datetime

    model_config = {"from_attributes": True}


class FeedbackCreate(BaseModel):
    verdict: FeedbackVerdict
    note: str | None = Field(default=None, max_length=2000)


class FeedbackRead(BaseModel):
    id: uuid.UUID
    analysis_id: uuid.UUID
    user_id: uuid.UUID
    verdict: FeedbackVerdict
    note: str | None
    applied: bool
    created_at: datetime

    model_config = {"from_attributes": True}
