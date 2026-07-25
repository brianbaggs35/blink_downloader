"""Admin-editable runtime settings — currently just the clip storage location."""

import asyncio
import os
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.logs import get_logger
from app.settings.schemas import StorageSettingsRead, StorageSettingsUpdate
from app.settings.service import get_app_settings, set_storage_dir
from app.users.auth import current_superuser

logger = get_logger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/storage", response_model=StorageSettingsRead)
async def get_storage_settings(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> StorageSettingsRead:
    row = await get_app_settings(session)
    if row.storage_dir:
        return StorageSettingsRead(storage_dir=row.storage_dir, is_default=False)
    return StorageSettingsRead(storage_dir=str(get_settings().storage_dir), is_default=True)


@router.patch("/storage", response_model=StorageSettingsRead)
async def update_storage_settings(
    payload: StorageSettingsUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> StorageSettingsRead:
    if payload.storage_dir is not None and not await _is_writable_directory(payload.storage_dir):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"'{payload.storage_dir}' does not exist or is not writable by the "
                "backend container. Existing clips are not moved when you change this."
            ),
        )
    row = await set_storage_dir(session, payload.storage_dir)
    logger.info("settings.storage_dir_updated", storage_dir=payload.storage_dir)
    if row.storage_dir:
        return StorageSettingsRead(storage_dir=row.storage_dir, is_default=False)
    return StorageSettingsRead(storage_dir=str(get_settings().storage_dir), is_default=True)


async def _is_writable_directory(raw_path: str) -> bool:
    def check() -> bool:
        path = Path(raw_path)
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError:
            return False
        return os.access(path, os.W_OK)

    return await asyncio.to_thread(check)
