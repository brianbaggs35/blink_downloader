"""UserManager: password policy and lifecycle hooks."""

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from fastapi_users import BaseUserManager, InvalidPasswordException, UUIDIDMixin, schemas
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.logs import get_logger
from app.users.models import User

logger = get_logger(__name__)

MIN_PASSWORD_LENGTH = 12


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    def __init__(self, user_db: SQLAlchemyUserDatabase[User, uuid.UUID]) -> None:
        super().__init__(user_db)
        settings = get_settings()
        self.reset_password_token_secret = settings.secret_key
        self.verification_token_secret = settings.secret_key

    async def validate_password(self, password: str, user: schemas.BaseUserCreate | User) -> None:
        if len(password) < MIN_PASSWORD_LENGTH:
            raise InvalidPasswordException(
                reason=f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
            )
        if user.email.lower() in password.lower():
            raise InvalidPasswordException(reason="Password must not contain your email address.")

    async def on_after_login(self, user: User, *args: object, **kwargs: object) -> None:
        logger.info("auth.login", user_id=str(user.id))


async def get_user_db(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AsyncIterator[SQLAlchemyUserDatabase[User, uuid.UUID]]:
    yield SQLAlchemyUserDatabase(session, User)


async def get_user_manager(
    user_db: Annotated[SQLAlchemyUserDatabase[User, uuid.UUID], Depends(get_user_db)],
) -> AsyncIterator[UserManager]:
    yield UserManager(user_db)
