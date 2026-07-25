"""User and session-token tables."""

import uuid
from datetime import datetime

from fastapi_users_db_sqlalchemy import SQLAlchemyBaseUserTableUUID
from fastapi_users_db_sqlalchemy.access_token import SQLAlchemyBaseAccessTokenTableUUID
from fastapi_users_db_sqlalchemy.generics import GUID
from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class User(SQLAlchemyBaseUserTableUUID, Base):
    __tablename__ = "users"

    display_name: Mapped[str] = mapped_column(String(120), default="", server_default="")
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", server_default="UTC")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AccessToken(SQLAlchemyBaseAccessTokenTableUUID, Base):
    """Server-side session token: revocable by deleting the row."""

    __tablename__ = "access_tokens"

    # The base class points its FK at a table named "user"; ours is "users".
    user_id: Mapped[uuid.UUID] = mapped_column(  # pyright: ignore[reportIncompatibleVariableOverride, reportGeneralTypeIssues]
        GUID, ForeignKey("users.id", ondelete="cascade"), nullable=False
    )
