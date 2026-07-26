"""Pydantic schemas for the user API surface."""

import uuid

from fastapi_users import schemas
from pydantic import BaseModel, EmailStr, Field

from app.users.models import LandingPage


class UserRead(schemas.BaseUser[uuid.UUID]):
    display_name: str
    timezone: str
    default_landing_page: LandingPage


class UserCreate(schemas.BaseUserCreate):
    display_name: str = ""
    timezone: str = "UTC"


class UserUpdate(schemas.BaseUserUpdate):
    display_name: str | None = None
    timezone: str | None = None
    default_landing_page: LandingPage | None = None


class SetupRequest(BaseModel):
    """First-run bootstrap of the administrator account."""

    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    display_name: str = Field(default="", max_length=120)


class SetupStatus(BaseModel):
    initialized: bool
