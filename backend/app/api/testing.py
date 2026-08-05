"""Test-only endpoint for resetting the e2e stack to a known data baseline
between Playwright tests. Never mounted unless
Settings.enable_test_reset_endpoint is explicitly true - see create_app().
No auth dependency: must be callable pre-login (e.g. before auth.spec.ts's
signed-out scenarios), which is exactly why true absence in every other
environment matters more than a permission check would."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.testing.seed import reset_data

router = APIRouter(prefix="/testing", tags=["testing"])


@router.post("/reset", status_code=status.HTTP_204_NO_CONTENT)
async def reset(session: Annotated[AsyncSession, Depends(get_session)]) -> None:
    await reset_data(session)
