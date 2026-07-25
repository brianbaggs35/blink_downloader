"""Pydantic schemas for the Biometrics API surface."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.biometrics.models import (
    DEFAULT_RECOGNITION_THRESHOLD,
    ExecutionProviderPreference,
    ModelPack,
)


class RecognizedPersonRead(BaseModel):
    """Embedded on ClipRead (see app.blink.schemas) so the Library grid and
    clip modal can show who was recognized without a separate round trip."""

    id: uuid.UUID
    name: str


class PersonRead(BaseModel):
    id: uuid.UUID
    name: str
    has_thumbnail: bool
    face_count: int
    created_at: datetime
    updated_at: datetime


class PersonCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class PersonUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class FaceEmbeddingRead(BaseModel):
    id: uuid.UUID
    source_clip_id: uuid.UUID | None
    source_frame_seconds: float | None
    created_at: datetime

    model_config = {"from_attributes": True}


class DetectedFaceRead(BaseModel):
    """A face found in a preview frame, for the enrollment UI to draw boxes
    over and let the household member pick one — never includes the raw
    embedding, which has no use client-side."""

    bbox: tuple[float, float, float, float]
    confidence: float


class EnrollFaceRequest(BaseModel):
    clip_id: uuid.UUID
    frame_seconds: float = Field(ge=0)
    bbox: tuple[float, float, float, float] = Field(
        description="The detected face (from the preview response) to enroll."
    )


class BiometricsSettingsRead(BaseModel):
    enabled: bool
    model_pack: ModelPack
    execution_provider_preference: ExecutionProviderPreference
    recognition_threshold: float
    available_providers: list[str]
    updated_at: datetime


class BiometricsSettingsUpdate(BaseModel):
    enabled: bool = False
    model_pack: ModelPack = ModelPack.BUFFALO_L
    execution_provider_preference: ExecutionProviderPreference = ExecutionProviderPreference.AUTO
    recognition_threshold: float = Field(default=DEFAULT_RECOGNITION_THRESHOLD, ge=0.0, le=1.0)
