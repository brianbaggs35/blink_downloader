"""AI analysis pipeline tables: settings, results, usage, feedback, learned
per-camera baselines, and the typed-event ledger they all feed.

Provider API keys are encrypted at rest (see :mod:`app.security.crypto`),
same as Blink credentials — nothing here ever holds a plaintext key.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, str_enum

SINGLETON_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


class AIProviderKind(StrEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OLLAMA = "ollama"
    OLLAMA_CLOUD = "ollama_cloud"
    MOONDREAM = "moondream"
    MOONDREAM_CLOUD = "moondream_cloud"


class AnalysisTier(StrEnum):
    TIER1 = "tier1"
    TIER2 = "tier2"


class SuspicionLabel(StrEnum):
    ROUTINE = "routine"
    UNCERTAIN = "uncertain"
    SUSPICIOUS = "suspicious"


class FeedbackVerdict(StrEnum):
    CORRECT = "correct"
    FALSE_POSITIVE = "false_positive"  # flagged suspicious, household says it wasn't
    FALSE_NEGATIVE = "false_negative"  # called routine, household says it was suspicious


class EventType(StrEnum):
    PERSON_DETECTED = "person_detected"
    VEHICLE_DETECTED = "vehicle_detected"
    ANIMAL_DETECTED = "animal_detected"
    PACKAGE_DETECTED = "package_detected"
    UNKNOWN_DETECTED = "unknown_detected"
    VEHICLE_PROXIMITY_BREACH = "vehicle_proximity_breach"
    SUSPICIOUS_ACTIVITY = "suspicious_activity"


class AISettings(Base):
    """Singleton row (fixed id, like :class:`app.settings.models.AppSettings`)."""

    __tablename__ = "ai_settings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    tier1_provider: Mapped[AIProviderKind | None] = mapped_column(
        str_enum(AIProviderKind, "ai_provider_kind")
    )
    tier1_model: Mapped[str | None] = mapped_column(Text)
    tier1_encrypted_api_key: Mapped[str | None] = mapped_column(Text)
    tier1_base_url: Mapped[str | None] = mapped_column(Text)

    tier2_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    tier2_provider: Mapped[AIProviderKind | None] = mapped_column(
        str_enum(AIProviderKind, "ai_provider_kind")
    )
    tier2_model: Mapped[str | None] = mapped_column(Text)
    tier2_encrypted_api_key: Mapped[str | None] = mapped_column(Text)
    tier2_base_url: Mapped[str | None] = mapped_column(Text)
    tier2_linked_to_tier1: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    """When true, tier2_provider/tier2_encrypted_api_key/tier2_base_url are
    kept in lockstep with tier1's on every save (see
    app.ai.service.update_ai_settings) so a household can point tier2 at a
    stronger model from the same provider/account without re-entering the
    API key. tier2_model is always independent."""

    # Advanced (optional — sensible defaults let most households never touch
    # these): how many keyframes per clip, the tier1 suspicion score that
    # triggers tier2 escalation, and how many past corrections to fold into
    # the prompt as few-shot context.
    keyframes_per_clip: Mapped[int] = mapped_column(Integer, default=4, server_default="4")
    tier2_suspicion_threshold: Mapped[float] = mapped_column(
        Float, default=0.5, server_default="0.5"
    )
    feedback_context_count: Mapped[int] = mapped_column(Integer, default=5, server_default="5")

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Analysis(Base):
    __tablename__ = "analyses"
    __table_args__ = (
        Index("ix_analyses_clip_current", "clip_id", "is_current"),
        Index("ix_analyses_clip_id", "clip_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    clip_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clips.id", ondelete="cascade"), nullable=False
    )
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    summary: Mapped[str] = mapped_column(Text, nullable=False)
    suspicion_score: Mapped[float] = mapped_column(Float, nullable=False)
    suspicion_label: Mapped[SuspicionLabel] = mapped_column(
        str_enum(SuspicionLabel, "suspicion_label"), nullable=False
    )

    tier: Mapped[AnalysisTier] = mapped_column(str_enum(AnalysisTier, "analysis_tier"))
    escalated: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    tier1_provider: Mapped[AIProviderKind | None] = mapped_column(
        str_enum(AIProviderKind, "ai_provider_kind")
    )
    tier1_model: Mapped[str | None] = mapped_column(Text)
    tier2_provider: Mapped[AIProviderKind | None] = mapped_column(
        str_enum(AIProviderKind, "ai_provider_kind")
    )
    tier2_model: Mapped[str | None] = mapped_column(Text)

    # [{type, confidence, bbox: [x, y, w, h] normalized 0-1, label}, ...]
    detected_entities: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default="[]"
    )
    # Shape: vehicle_id, distance_feet, error_margin_feet, breached_threshold.
    # Null when no vehicle is registered on the clip's camera.
    vehicle_proximity: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    feedback: Mapped[list[Feedback]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )


class AIUsage(Base):
    __tablename__ = "ai_usage"
    __table_args__ = (Index("ix_ai_usage_created_at", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analyses.id", ondelete="set null")
    )
    clip_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clips.id", ondelete="cascade"), nullable=False
    )
    tier: Mapped[AnalysisTier] = mapped_column(
        str_enum(AnalysisTier, "analysis_tier"), nullable=False
    )
    provider: Mapped[AIProviderKind] = mapped_column(
        str_enum(AIProviderKind, "ai_provider_kind"), nullable=False
    )
    model: Mapped[str] = mapped_column(Text, nullable=False)

    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # How many keyframes this specific call sent - recorded per-row (not
    # read live off AISettings.keyframes_per_clip) since that setting can
    # change over time and would make historical totals wrong.
    frame_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    estimated_cost_usd: Mapped[float] = mapped_column(
        Numeric(10, 6, asdecimal=False), default=0, server_default="0"
    )
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CameraBaseline(Base):
    """One row per camera: a rolling hour-of-day x entity-type histogram the
    household's own history builds up over time, used to damp suspicion for
    patterns a camera has learned are routine."""

    __tablename__ = "camera_baselines"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    camera_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cameras.id", ondelete="cascade"),
        nullable=False,
        unique=True,
    )
    # {"0": {"person": 3, "vehicle": 1}, "1": {...}, ..., "23": {...}}
    hourly_entity_counts: Mapped[dict[str, dict[str, int]]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    total_observations: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = (Index("ix_feedback_analysis_id", "analysis_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analyses.id", ondelete="cascade"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="cascade"), nullable=False
    )
    verdict: Mapped[FeedbackVerdict] = mapped_column(
        str_enum(FeedbackVerdict, "feedback_verdict"), nullable=False
    )
    note: Mapped[str | None] = mapped_column(Text)
    applied: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    analysis: Mapped[Analysis] = relationship(back_populates="feedback")


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_camera_occurred", "camera_id", "occurred_at"),
        UniqueConstraint("clip_id", "event_type", name="uq_events_clip_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    clip_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clips.id", ondelete="cascade"), nullable=False
    )
    analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analyses.id", ondelete="set null")
    )
    camera_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cameras.id", ondelete="cascade"), nullable=False
    )
    event_type: Mapped[EventType] = mapped_column(str_enum(EventType, "event_type"), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    event_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
