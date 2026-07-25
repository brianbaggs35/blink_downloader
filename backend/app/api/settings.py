"""Admin-editable runtime settings: clip storage location and AI provider
configuration."""

import asyncio
import os
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AISettings
from app.ai.providers import AIProviderError, build_provider
from app.ai.schemas import (
    AIConnectionTestRequest,
    AIConnectionTestResponse,
    AISettingsRead,
    AISettingsUpdate,
)
from app.ai.service import get_ai_settings, update_ai_settings
from app.config import get_settings
from app.db import get_session
from app.logs import get_logger
from app.security.crypto import SecretBox
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


def _ai_settings_read(row: AISettings) -> AISettingsRead:
    return AISettingsRead(
        enabled=row.enabled,
        tier1_provider=row.tier1_provider,
        tier1_model=row.tier1_model,
        tier1_api_key_set=bool(row.tier1_encrypted_api_key),
        tier1_base_url=row.tier1_base_url,
        tier2_enabled=row.tier2_enabled,
        tier2_provider=row.tier2_provider,
        tier2_model=row.tier2_model,
        tier2_api_key_set=bool(row.tier2_encrypted_api_key),
        tier2_base_url=row.tier2_base_url,
        keyframes_per_clip=row.keyframes_per_clip,
        tier2_suspicion_threshold=row.tier2_suspicion_threshold,
        feedback_context_count=row.feedback_context_count,
    )


@router.get("/ai", response_model=AISettingsRead)
async def get_ai_provider_settings(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> AISettingsRead:
    return _ai_settings_read(await get_ai_settings(session))


@router.put("/ai", response_model=AISettingsRead)
async def update_ai_provider_settings(
    payload: AISettingsUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> AISettingsRead:
    row = await update_ai_settings(session, payload, get_settings().encryption_key)
    logger.info("settings.ai_updated", enabled=row.enabled, tier1_provider=row.tier1_provider)
    return _ai_settings_read(row)


@router.post("/ai/test-connection", response_model=AIConnectionTestResponse)
async def test_ai_connection(
    payload: AIConnectionTestRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> AIConnectionTestResponse:
    api_key = payload.api_key
    if not api_key:
        row = await get_ai_settings(session)
        encrypted = (
            row.tier1_encrypted_api_key if payload.tier == "tier1" else row.tier2_encrypted_api_key
        )
        if encrypted:
            api_key = SecretBox(get_settings().encryption_key).decrypt(encrypted)

    try:
        provider = build_provider(payload.provider, payload.model, api_key, payload.base_url)
        await provider.test_connection()
    except AIProviderError as exc:
        return AIConnectionTestResponse(ok=False, detail=str(exc))
    return AIConnectionTestResponse(ok=True, detail=None)
