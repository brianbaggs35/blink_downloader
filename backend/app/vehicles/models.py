"""Registered vehicles: a per-camera protected outline + proximity threshold.

One camera can protect at most one vehicle today (a household's driveway
camera watches its one car) — the unique constraint keeps that explicit
rather than silently allowing ambiguous multi-vehicle overlap on one frame.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

DEFAULT_VEHICLE_LENGTH_FEET = 15.0
DEFAULT_DISTANCE_THRESHOLD_FEET = 6.0


class Vehicle(Base):
    __tablename__ = "vehicles"
    __table_args__ = (UniqueConstraint("camera_id", name="uq_vehicles_camera"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    camera_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cameras.id", ondelete="cascade"), nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Freeform outline drawn over a reference frame: [[x, y], ...] normalized
    # 0-1 so it stays valid if the camera's stream resolution ever changes.
    outline_points: Mapped[list[list[float]]] = mapped_column(
        JSONB, default=list, server_default="[]"
    )
    reference_frame_path: Mapped[str | None] = mapped_column(Text)

    estimated_length_feet: Mapped[float] = mapped_column(
        Float, default=DEFAULT_VEHICLE_LENGTH_FEET, server_default=str(DEFAULT_VEHICLE_LENGTH_FEET)
    )
    distance_threshold_feet: Mapped[float] = mapped_column(
        Float,
        default=DEFAULT_DISTANCE_THRESHOLD_FEET,
        server_default=str(DEFAULT_DISTANCE_THRESHOLD_FEET),
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ProximityEvent(Base):
    """A single "someone was within the threshold" occurrence — the Vehicles
    tab's history and alert delivery both read this rather than re-deriving
    it from analyses."""

    __tablename__ = "proximity_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="cascade"), nullable=False
    )
    clip_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clips.id", ondelete="cascade"), nullable=False
    )
    distance_feet: Mapped[float] = mapped_column(Float, nullable=False)
    error_margin_feet: Mapped[float] = mapped_column(Float, nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
