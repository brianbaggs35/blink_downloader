"""Authentication backend: HttpOnly cookie carrying a revocable DB session token."""

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from fastapi_users import FastAPIUsers
from fastapi_users.authentication import AuthenticationBackend, CookieTransport
from fastapi_users.authentication.strategy.db import AccessTokenDatabase, DatabaseStrategy
from fastapi_users_db_sqlalchemy.access_token import SQLAlchemyAccessTokenDatabase
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.users.manager import get_user_manager
from app.users.models import AccessToken, User


def build_cookie_transport() -> CookieTransport:
    settings = get_settings()
    return CookieTransport(
        cookie_name=settings.cookie_name,
        cookie_max_age=settings.session_lifetime_seconds,
        cookie_secure=settings.cookie_secure,
        cookie_httponly=True,
        cookie_samesite="lax",
    )


async def get_access_token_db(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AsyncIterator[SQLAlchemyAccessTokenDatabase[AccessToken]]:
    yield SQLAlchemyAccessTokenDatabase(session, AccessToken)


def get_database_strategy(
    access_token_db: Annotated[AccessTokenDatabase[AccessToken], Depends(get_access_token_db)],
) -> DatabaseStrategy[User, uuid.UUID, AccessToken]:
    return DatabaseStrategy(
        access_token_db, lifetime_seconds=get_settings().session_lifetime_seconds
    )


auth_backend = AuthenticationBackend(
    name="cookie",
    transport=build_cookie_transport(),
    get_strategy=get_database_strategy,
)

fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [auth_backend])

current_active_user = fastapi_users.current_user(active=True)
current_superuser = fastapi_users.current_user(active=True, superuser=True)
