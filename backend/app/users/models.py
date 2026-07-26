"""User and session-token tables."""

import uuid
from datetime import datetime
from enum import StrEnum

from fastapi_users_db_sqlalchemy import SQLAlchemyBaseUserTableUUID
from fastapi_users_db_sqlalchemy.access_token import SQLAlchemyBaseAccessTokenTableUUID
from fastapi_users_db_sqlalchemy.generics import GUID
from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.db import str_enum as _str_enum


class LandingPage(StrEnum):
    LIBRARY = "library"
    SECURITY_FEED = "security_feed"


class User(SQLAlchemyBaseUserTableUUID, Base):
    __tablename__ = "users"

    display_name: Mapped[str] = mapped_column(String(120), default="", server_default="")
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", server_default="UTC")
    default_landing_page: Mapped[LandingPage] = mapped_column(
        _str_enum(LandingPage, "user_landing_page", length=20),
        default=LandingPage.LIBRARY,
        server_default=LandingPage.LIBRARY.name,
    )
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
