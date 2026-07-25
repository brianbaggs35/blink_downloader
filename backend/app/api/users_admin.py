"""Admin-only user management: list + invite. fastapi-users' own router
(mounted at the same /users prefix) already covers GET/PATCH /me and the
superuser-gated GET/PATCH/DELETE /{id} — this adds the two operations it
doesn't provide: listing everyone, and creating a new account.

There is no email-verification flow in this app (no open registration to
guard against), so admin-created accounts are verified immediately.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi_users import InvalidPasswordException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.logs import get_logger
from app.users.auth import current_superuser
from app.users.manager import UserManager, get_user_manager
from app.users.models import User
from app.users.schemas import UserCreate, UserRead

logger = get_logger(__name__)

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserRead], dependencies=[Depends(current_superuser)])
async def list_users(session: Annotated[AsyncSession, Depends(get_session)]) -> list[User]:
    result = await session.execute(select(User).order_by(User.created_at))
    return list(result.scalars().all())


@router.post(
    "",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(current_superuser)],
)
async def create_user(
    payload: UserCreate,
    user_manager: Annotated[UserManager, Depends(get_user_manager)],
) -> User:
    try:
        user = await user_manager.create(
            UserCreate(
                email=payload.email,
                password=payload.password,
                display_name=payload.display_name,
                timezone=payload.timezone,
                is_superuser=payload.is_superuser,
                is_verified=True,
            ),
            safe=False,
        )
    except InvalidPasswordException as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.reason) from exc
    logger.info("users.created_by_admin", user_id=str(user.id), is_superuser=user.is_superuser)
    return user
