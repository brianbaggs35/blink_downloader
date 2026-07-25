"""Pydantic schemas for the Vehicles API surface."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.vehicles.models import DEFAULT_DISTANCE_THRESHOLD_FEET, DEFAULT_VEHICLE_LENGTH_FEET


class VehicleRead(BaseModel):
    id: uuid.UUID
    camera_id: uuid.UUID
    camera_name: str
    description: str
    outline_points: list[list[float]]
    has_reference_frame: bool
    estimated_length_feet: float
    distance_threshold_feet: float
    enabled: bool
    updated_at: datetime


class VehicleUpdate(BaseModel):
    description: str = Field(min_length=1, max_length=200)
    outline_points: list[tuple[float, float]] = Field(min_length=3, max_length=200)
    estimated_length_feet: float = Field(default=DEFAULT_VEHICLE_LENGTH_FEET, gt=0, le=100)
    distance_threshold_feet: float = Field(default=DEFAULT_DISTANCE_THRESHOLD_FEET, gt=0, le=100)
    enabled: bool = True

    @field_validator("outline_points")
    @classmethod
    def _points_must_be_normalized(
        cls, value: list[tuple[float, float]]
    ) -> list[tuple[float, float]]:
        for x, y in value:
            if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
                raise ValueError("outline_points must be normalized to the 0-1 range.")
        return value


class ProximityEventRead(BaseModel):
    id: uuid.UUID
    clip_id: uuid.UUID
    distance_feet: float
    error_margin_feet: float
    occurred_at: datetime

    model_config = {"from_attributes": True}
