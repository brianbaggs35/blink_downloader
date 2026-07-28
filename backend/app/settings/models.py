"""A single admin-editable settings row.

There is exactly one, at a fixed id, so reading/writing it never needs a
lookup — see :func:`app.settings.service.get_app_settings`.
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

SINGLETON_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


class AppSettings(Base):
    __tablename__ = "app_settings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    storage_dir: Mapped[str | None] = mapped_column(Text)
    # BigInteger (not Integer, unlike file_size_bytes elsewhere) - a quota is
    # meant to express whole-disk budgets like "500 GB", which overflows a
    # 32-bit column almost immediately. Null means unlimited.
    local_storage_quota_bytes: Mapped[int | None] = mapped_column(BigInteger)
    # All three null by default (falls back to the BLINK_-prefixed env var in
    # app.config.Settings) - overridable at runtime without a redeploy, same
    # null-means-default convention as storage_dir above.
    blink_sync_interval_seconds: Mapped[int | None] = mapped_column(Integer)
    blink_initial_sync_days: Mapped[int | None] = mapped_column(Integer)
    blink_auto_analyze_limit: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
