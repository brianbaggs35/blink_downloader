"""Live View and Security Feed settings."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.livefeed.schemas import (
    LiveViewSettingsRead,
    LiveViewSettingsUpdate,
    SecurityFeedSettingsRead,
    SecurityFeedSettingsUpdate,
)
from app.livefeed.service import (
    get_live_view_settings,
    get_security_feed_settings,
    update_live_view_settings,
    update_security_feed_settings,
)
from app.logs import get_logger
from app.users.auth import current_active_user, current_superuser

logger = get_logger(__name__)

router = APIRouter(prefix="/livefeed", tags=["livefeed"])


@router.get("/settings/live-view", response_model=LiveViewSettingsRead)
async def read_live_view_settings(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_active_user)],
) -> LiveViewSettingsRead:
    row = await get_live_view_settings(session)
    return LiveViewSettingsRead(
        default_camera_id=row.default_camera_id,
        auto_refresh_enabled=row.auto_refresh_enabled,
        auto_refresh_interval_seconds=row.auto_refresh_interval_seconds,
    )


@router.put("/settings/live-view", response_model=LiveViewSettingsRead)
async def write_live_view_settings(
    payload: LiveViewSettingsUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> LiveViewSettingsRead:
    row = await update_live_view_settings(session, payload)
    logger.info("livefeed.live_view_settings_updated")
    return LiveViewSettingsRead(
        default_camera_id=row.default_camera_id,
        auto_refresh_enabled=row.auto_refresh_enabled,
        auto_refresh_interval_seconds=row.auto_refresh_interval_seconds,
    )


@router.get("/settings/security-feed", response_model=SecurityFeedSettingsRead)
async def read_security_feed_settings(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_active_user)],
) -> SecurityFeedSettingsRead:
    row = await get_security_feed_settings(session)
    return SecurityFeedSettingsRead(
        camera_ids=[uuid.UUID(c) for c in row.camera_ids],
        columns=row.columns,
        refresh_interval_seconds=row.refresh_interval_seconds,
        refresh_mode=row.refresh_mode,
    )


@router.put("/settings/security-feed", response_model=SecurityFeedSettingsRead)
async def write_security_feed_settings(
    payload: SecurityFeedSettingsUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> SecurityFeedSettingsRead:
    row = await update_security_feed_settings(session, payload)
    logger.info("livefeed.security_feed_settings_updated")
    return SecurityFeedSettingsRead(
        camera_ids=[uuid.UUID(c) for c in row.camera_ids],
        columns=row.columns,
        refresh_interval_seconds=row.refresh_interval_seconds,
        refresh_mode=row.refresh_mode,
    )
