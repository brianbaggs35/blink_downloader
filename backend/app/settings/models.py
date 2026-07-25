"""A single admin-editable settings row.

There is exactly one, at a fixed id, so reading/writing it never needs a
lookup — see :func:`app.settings.service.get_app_settings`.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

SINGLETON_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


class AppSettings(Base):
    __tablename__ = "app_settings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    storage_dir: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
