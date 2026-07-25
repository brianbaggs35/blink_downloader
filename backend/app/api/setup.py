"""First-run bootstrap: create the administrator account exactly once.

There is no open self-registration anywhere in the API. Additional household
members are invited by the administrator (a later feature).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi_users import InvalidPasswordException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.logs import get_logger
from app.security.ratelimit import RateLimiter
from app.users.manager import UserManager, get_user_manager
from app.users.models import User
from app.users.schemas import SetupRequest, SetupStatus, UserCreate, UserRead

logger = get_logger(__name__)

router = APIRouter()

setup_rate_limit = RateLimiter(times=5, seconds=60, scope="setup")


async def _user_count(session: AsyncSession) -> int:
    result = await session.execute(select(func.count()).select_from(User))
    return result.scalar_one()


@router.get("/setup/status", response_model=SetupStatus)
async def setup_status(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SetupStatus:
    return SetupStatus(initialized=await _user_count(session) > 0)


@router.post(
    "/setup",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(setup_rate_limit)],
)
async def run_setup(
    payload: SetupRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    user_manager: Annotated[UserManager, Depends(get_user_manager)],
) -> User:
    if await _user_count(session) > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Setup has already been completed.",
        )
    try:
        user = await user_manager.create(
            UserCreate(
                email=payload.email,
                password=payload.password,
                display_name=payload.display_name,
                is_superuser=True,
                is_verified=True,
            ),
            safe=False,
        )
    except InvalidPasswordException as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.reason) from exc
    logger.info("setup.admin_created", user_id=str(user.id))
    return user
