"""Local-only facial recognition: enrolled people, their face embeddings,
and per-clip recognition records.

Everything in this module is designed to never leave the local network: face
crops and embeddings are computed here and matched here (see
:mod:`app.biometrics.recognition`), and are never sent to any AI provider.
The VLM analysis pipeline only ever learns a recognized person's *name* as a
local, post-hoc label rewrite — see :mod:`app.ai.service` — never a face
image or embedding.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, str_enum

SINGLETON_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")

# All four insightface "buffalo_*" model packs share the same 512-dim ArcFace
# recognition head; only detection/recognition backbone size differs.
FACE_EMBEDDING_DIM = 512

DEFAULT_RECOGNITION_THRESHOLD = 0.4


class ModelPack(StrEnum):
    """insightface named model packs, smallest/fastest to largest/most
    accurate. Chosen in Settings based on available CPU/GPU headroom."""

    BUFFALO_SC = "buffalo_sc"
    BUFFALO_S = "buffalo_s"
    BUFFALO_M = "buffalo_m"
    BUFFALO_L = "buffalo_l"


class ExecutionProviderPreference(StrEnum):
    """"auto" picks CUDA when onnxruntime reports it's available, else falls
    back to CPU (see app.biometrics.recognition) — GPU is never assumed."""

    AUTO = "auto"
    CPU = "cpu"


class Person(Base):
    """An enrolled household member or known visitor."""

    __tablename__ = "people"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    thumbnail_path: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    face_embeddings: Mapped[list[FaceEmbedding]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )


class FaceEmbedding(Base):
    """One enrolled face sample. A person usually has several, cropped from
    different clips/frames for angle and lighting variety — recognition
    matches a candidate face against all of them (see
    app.biometrics.recognition) and takes the closest hit."""

    __tablename__ = "face_embeddings"
    __table_args__ = (Index("ix_face_embeddings_person_id", "person_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("people.id", ondelete="cascade"), nullable=False
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(FACE_EMBEDDING_DIM), nullable=False)

    # Provenance for the enrollment UI's "where did this sample come from"
    # display. Null when the sample came from an uploaded photo rather than
    # a clip frame.
    source_clip_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clips.id", ondelete="set null")
    )
    source_frame_seconds: Mapped[float | None] = mapped_column(Float)
    thumbnail_path: Mapped[str] = mapped_column(Text, nullable=False)

    # Reserved for a future "this isn't them" correction flow, mirroring
    # app.ai.models.Feedback: a negative sample would push the match score
    # for a known false-positive face down without deleting the enrollment.
    # Not yet surfaced in the UI.
    is_negative: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    person: Mapped[Person] = relationship(back_populates="face_embeddings")


class RecognizedFace(Base):
    """One "this enrolled person appears in this clip" record, upserted on
    every (re-)analysis. Kept as its own table rather than folded into
    Analysis.detected_entities so a person's appearance history survives
    clip re-analysis and Library filtering doesn't need to unpack JSON."""

    __tablename__ = "recognized_faces"
    __table_args__ = (
        UniqueConstraint("clip_id", "person_id", name="uq_recognized_faces_clip_person"),
        Index("ix_recognized_faces_person_id", "person_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    clip_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clips.id", ondelete="cascade"), nullable=False
    )
    analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analyses.id", ondelete="set null")
    )
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("people.id", ondelete="cascade"), nullable=False
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    person: Mapped[Person] = relationship()


class BiometricsSettings(Base):
    """Singleton row (fixed id, like app.ai.models.AISettings)."""

    __tablename__ = "biometrics_settings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    model_pack: Mapped[ModelPack] = mapped_column(
        str_enum(ModelPack, "biometrics_model_pack"),
        default=ModelPack.BUFFALO_L,
        server_default=ModelPack.BUFFALO_L.name,
        nullable=False,
    )
    execution_provider_preference: Mapped[ExecutionProviderPreference] = mapped_column(
        str_enum(ExecutionProviderPreference, "biometrics_execution_provider_preference"),
        default=ExecutionProviderPreference.AUTO,
        server_default=ExecutionProviderPreference.AUTO.name,
        nullable=False,
    )
    recognition_threshold: Mapped[float] = mapped_column(
        Float,
        default=DEFAULT_RECOGNITION_THRESHOLD,
        server_default=str(DEFAULT_RECOGNITION_THRESHOLD),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
