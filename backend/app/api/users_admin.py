"""Admin-only user management: list, invite, edit, and remove.

fastapi-users' own router (mounted at the same /users prefix) covers
GET/PATCH /me (self-service - see app.users.schemas.UserUpdate, which
includes password) and GET /{id}. Its generic PATCH/DELETE /{id} are
dropped in app.api in favor of the guarded versions here: the generic
ones have no protection against locking a household out of its own admin
account (demoting or deleting the last superuser) or an admin deleting
their own session out from under themselves.

There is no email-verification flow in this app (no open registration to
guard against), so admin-created accounts are verified immediately.
"""

# fastapi_users_db_sqlalchemy's SQLAlchemyBaseUserTable deliberately types
# is_active/is_superuser as plain `bool` under TYPE_CHECKING (trading away
# class-level SQLAlchemy expression typing for cleaner instance-level
# ergonomics elsewhere - confirmed by reading its installed source), which
# makes User.is_superuser.is_(...)/User.is_active.is_(...) below look like
# calling .is_() on a bool to the type checker. Same class of gap as
# AccessToken.user_id's FK override in app.users.models.
# pyright: reportUnknownArgumentType=false
# pyright: reportAttributeAccessIssue=false
# pyright: reportUnknownMemberType=false
# pyright: reportArgumentType=false

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi_users import InvalidPasswordException
from fastapi_users.exceptions import UserAlreadyExists
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.logs import get_logger
from app.users.auth import current_superuser
from app.users.manager import UserManager, get_user_manager
from app.users.models import User
from app.users.schemas import UserCreate, UserRead, UserUpdate

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
    except UserAlreadyExists as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email already exists.",
        ) from exc
    logger.info("users.created_by_admin", user_id=str(user.id), is_superuser=user.is_superuser)
    return user


class AdminUserUpdate(BaseModel):
    """Name/role/(optional) password reset - deliberately narrower than
    fastapi-users' own UserUpdate schema (no email/timezone/is_active
    editing here). Email in particular is out of scope of what was asked
    for and, as the login-identifying field, an easy thing to get wrong
    from a "quick edit" modal."""

    display_name: str = Field(max_length=120)
    is_superuser: bool
    password: str | None = None


async def _get_user_or_404(session: AsyncSession, user_id: uuid.UUID) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return user


async def _remaining_admins_if_this_one_is_removed(
    session: AsyncSession, target_id: uuid.UUID
) -> int:
    """How many *other* enabled administrators would still exist - a
    disabled admin can't log in, so doesn't count as real fallback access
    either."""
    stmt = (
        select(func.count())
        .select_from(User)
        .where(User.is_superuser.is_(True), User.is_active.is_(True), User.id != target_id)
    )
    return (await session.execute(stmt)).scalar_one()


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: uuid.UUID,
    payload: AdminUserUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    user_manager: Annotated[UserManager, Depends(get_user_manager)],
    _current_user: Annotated[User, Depends(current_superuser)],
) -> User:
    target = await _get_user_or_404(session, user_id)
    if (
        target.is_superuser
        and not payload.is_superuser
        and await _remaining_admins_if_this_one_is_removed(session, target.id) == 0
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove the last administrator.",
        )
    # fastapi-users' update_dict is built from *set* fields (exclude_unset),
    # not non-None ones - passing password=None here would still count as
    # "set" and reach _update()'s password branch, so the key is left out
    # entirely rather than passed through as None for "leave it alone".
    update_fields: dict[str, str | bool] = {
        "display_name": payload.display_name,
        "is_superuser": payload.is_superuser,
    }
    if payload.password is not None:
        update_fields["password"] = payload.password
    update = UserUpdate(**update_fields)
    try:
        updated = await user_manager.update(update, target, safe=False)
    except InvalidPasswordException as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.reason) from exc
    logger.info("users.updated_by_admin", user_id=str(target.id), is_superuser=updated.is_superuser)
    return updated


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user_manager: Annotated[UserManager, Depends(get_user_manager)],
    current_user: Annotated[User, Depends(current_superuser)],
) -> None:
    target = await _get_user_or_404(session, user_id)
    if target.id == current_user.id:
        # Also what makes the last-admin guard on update_user() unnecessary
        # here: current_superuser guarantees the caller is themselves an
        # active superuser, and this check guarantees they're not the
        # target - so a delete can never take the admin count to zero,
        # only self-demotion-as-the-sole-admin (PATCH) can.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You can't delete your own account - ask another administrator to do it.",
        )
    await user_manager.delete(target)
    logger.info("users.deleted_by_admin", user_id=str(user_id))
