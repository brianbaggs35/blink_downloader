"""Admin-editable runtime settings: clip storage location and AI provider
configuration."""

import asyncio
import os
from io import BytesIO
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AIProviderKind, AISettings
from app.ai.providers import (
    DEFAULT_OLLAMA_CLOUD_URL,
    DEFAULT_OLLAMA_LOCAL_URL,
    AIProviderError,
    AnalysisRequest,
    OllamaProvider,
    build_provider,
)
from app.ai.schemas import (
    AIConnectionTestRequest,
    AIConnectionTestResponse,
    AIModelListRequest,
    AIModelListResponse,
    AISettingsRead,
    AISettingsUpdate,
)
from app.ai.service import get_ai_settings, update_ai_settings
from app.config import get_settings
from app.db import get_session
from app.logs import get_logger
from app.security.crypto import SecretBox
from app.settings.models import AppSettings
from app.settings.schemas import (
    BlinkSyncSettingsRead,
    BlinkSyncSettingsUpdate,
    StorageBrowseEntry,
    StorageBrowseResponse,
    StorageCreateFolderRequest,
    StorageRenameFolderRequest,
    StorageSettingsRead,
    StorageSettingsUpdate,
)
from app.settings.service import (
    get_app_settings,
    resolve_storage_dir,
    set_blink_sync_settings,
    set_local_storage_quota_bytes,
    set_storage_dir,
)
from app.users.auth import current_superuser

logger = get_logger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])


def _storage_settings_read(row: AppSettings) -> StorageSettingsRead:
    if row.storage_dir:
        return StorageSettingsRead(
            storage_dir=row.storage_dir,
            is_default=False,
            local_storage_quota_bytes=row.local_storage_quota_bytes,
        )
    return StorageSettingsRead(
        storage_dir=str(get_settings().storage_dir),
        is_default=True,
        local_storage_quota_bytes=row.local_storage_quota_bytes,
    )


@router.get("/storage", response_model=StorageSettingsRead)
async def get_storage_settings(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> StorageSettingsRead:
    return _storage_settings_read(await get_app_settings(session))


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
    await set_storage_dir(session, payload.storage_dir)
    row = await set_local_storage_quota_bytes(session, payload.local_storage_quota_bytes)
    logger.info("settings.storage_dir_updated", storage_dir=payload.storage_dir)
    return _storage_settings_read(row)


@router.get("/storage/browse", response_model=StorageBrowseResponse)
async def browse_storage_directories(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
    path: str | None = None,
) -> StorageBrowseResponse:
    """Lists the subdirectories of `path` (default: the currently configured
    clip storage directory) so the Storage settings UI can offer a folder
    picker instead of a blind text field - the container can only ever see
    what's actually mounted into it, so this is scoped to browsing/creating
    within that, not a general host filesystem browser."""
    if path is None:
        path = str(await resolve_storage_dir(session, get_settings()))
    return await _list_directory(path)


@router.post(
    "/storage/browse",
    response_model=StorageBrowseResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_storage_directory(
    payload: StorageCreateFolderRequest,
    _user: Annotated[object, Depends(current_superuser)],
) -> StorageBrowseResponse:
    new_path = Path(payload.parent_path) / payload.name
    if not await _is_writable_directory(str(new_path)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Could not create '{new_path}' - check the parent path is valid "
                "and writable by the backend container."
            ),
        )
    logger.info("settings.storage_dir_folder_created", path=str(new_path))
    return await _list_directory(str(new_path))


@router.patch("/storage/browse", response_model=StorageBrowseResponse)
async def rename_storage_directory(
    payload: StorageRenameFolderRequest,
    _user: Annotated[object, Depends(current_superuser)],
) -> StorageBrowseResponse:
    old_path = Path(payload.path)
    new_path = old_path.parent / payload.new_name

    def do_rename() -> None:
        if not old_path.is_dir():
            msg = f"'{old_path}' does not exist or is not a directory."
            raise ValueError(msg)
        if new_path.exists():
            msg = f"'{new_path}' already exists."
            raise ValueError(msg)
        try:
            old_path.rename(new_path)
        except OSError as exc:
            msg = f"Could not rename '{old_path}': {exc}"
            raise ValueError(msg) from exc

    try:
        await asyncio.to_thread(do_rename)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    logger.info(
        "settings.storage_dir_folder_renamed", old_path=str(old_path), new_path=str(new_path)
    )
    return await _list_directory(str(old_path.parent))


@router.delete("/storage/browse", response_model=StorageBrowseResponse)
async def delete_storage_directory(
    _user: Annotated[object, Depends(current_superuser)],
    path: str,
) -> StorageBrowseResponse:
    target = Path(path)

    def do_delete() -> None:
        if not target.is_dir():
            msg = f"'{target}' does not exist or is not a directory."
            raise ValueError(msg)
        try:
            target.rmdir()
        except OSError as exc:
            msg = f"Could not delete '{target}' - it must be empty first ({exc})."
            raise ValueError(msg) from exc

    try:
        await asyncio.to_thread(do_delete)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    logger.info("settings.storage_dir_folder_deleted", path=str(target))
    return await _list_directory(str(target.parent))


def _blink_sync_settings_read(row: AppSettings) -> BlinkSyncSettingsRead:
    env = get_settings()
    return BlinkSyncSettingsRead(
        sync_interval_seconds=row.blink_sync_interval_seconds or env.blink_sync_interval_seconds,
        initial_sync_days=row.blink_initial_sync_days or env.blink_initial_sync_days,
        auto_analyze_limit=row.blink_auto_analyze_limit or env.blink_auto_analyze_limit,
        is_default=(
            row.blink_sync_interval_seconds is None
            and row.blink_initial_sync_days is None
            and row.blink_auto_analyze_limit is None
        ),
    )


@router.get("/blink-sync", response_model=BlinkSyncSettingsRead)
async def get_blink_sync_settings(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> BlinkSyncSettingsRead:
    return _blink_sync_settings_read(await get_app_settings(session))


@router.put("/blink-sync", response_model=BlinkSyncSettingsRead)
async def update_blink_sync_settings(
    payload: BlinkSyncSettingsUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> BlinkSyncSettingsRead:
    row = await set_blink_sync_settings(session, payload)
    logger.info(
        "settings.blink_sync_updated",
        sync_interval_seconds=row.blink_sync_interval_seconds,
        initial_sync_days=row.blink_initial_sync_days,
        auto_analyze_limit=row.blink_auto_analyze_limit,
    )
    return _blink_sync_settings_read(row)


async def _is_writable_directory(raw_path: str) -> bool:
    def check() -> bool:
        path = Path(raw_path)
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError:
            return False
        return os.access(path, os.W_OK)

    return await asyncio.to_thread(check)


async def _list_directory(raw_path: str) -> StorageBrowseResponse:
    def list_dirs() -> StorageBrowseResponse:
        path = Path(raw_path)
        if not path.is_absolute():
            msg = f"'{path}' is not an absolute path."
            raise ValueError(msg)
        if not path.is_dir():
            msg = f"'{path}' does not exist or is not a directory."
            raise ValueError(msg)
        try:
            entries = sorted(
                (p for p in path.iterdir() if p.is_dir() and not p.name.startswith(".")),
                key=lambda p: p.name.lower(),
            )
        except PermissionError as exc:
            msg = f"No permission to list '{path}'."
            raise ValueError(msg) from exc
        parent = path.parent
        return StorageBrowseResponse(
            path=str(path),
            parent_path=str(parent) if parent != path else None,
            directories=[StorageBrowseEntry(name=p.name, path=str(p)) for p in entries],
        )

    try:
        return await asyncio.to_thread(list_dirs)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


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
        tier2_linked_to_tier1=row.tier2_linked_to_tier1,
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


async def _resolve_saved_api_key(
    session: AsyncSession, tier: str, api_key: str | None
) -> str | None:
    if api_key:
        return api_key
    row = await get_ai_settings(session)
    encrypted = row.tier1_encrypted_api_key if tier == "tier1" else row.tier2_encrypted_api_key
    return SecretBox(get_settings().encryption_key).decrypt(encrypted) if encrypted else None


@router.post("/ai/test-connection", response_model=AIConnectionTestResponse)
async def test_ai_connection(
    payload: AIConnectionTestRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> AIConnectionTestResponse:
    api_key = await _resolve_saved_api_key(session, payload.tier, payload.api_key)
    try:
        provider = build_provider(payload.provider, payload.model, api_key, payload.base_url)
        await provider.test_connection()
    except AIProviderError as exc:
        return AIConnectionTestResponse(ok=False, detail=str(exc))
    return AIConnectionTestResponse(ok=True, detail=None)


def _sample_test_image() -> bytes:
    """A tiny synthetic keyframe - just enough for a provider to return a
    real (if unremarkable) analysis, so "test analysis" exercises the whole
    request/response contract rather than just reachability."""
    buffer = BytesIO()
    Image.new("RGB", (64, 64), color=(90, 90, 90)).save(buffer, format="JPEG")
    return buffer.getvalue()


@router.post("/ai/test-analysis", response_model=AIConnectionTestResponse)
async def test_ai_analysis(
    payload: AIConnectionTestRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> AIConnectionTestResponse:
    """Runs a real analyze() call against a blank sample image - unlike
    test-connection (reachability/auth only), this also proves the model
    name is valid and its response actually parses, at the cost of a real
    (tiny) inference call."""
    api_key = await _resolve_saved_api_key(session, payload.tier, payload.api_key)
    try:
        provider = build_provider(payload.provider, payload.model, api_key, payload.base_url)
        result = await provider.analyze(AnalysisRequest(images=[_sample_test_image()]))
    except AIProviderError as exc:
        return AIConnectionTestResponse(ok=False, detail=str(exc))
    return AIConnectionTestResponse(
        ok=True,
        detail=f'Model responded: "{result.summary}" (suspicion {result.suspicion_score:.2f}).',
    )


_OLLAMA_KINDS = (AIProviderKind.OLLAMA, AIProviderKind.OLLAMA_CLOUD)


@router.post("/ai/list-models")
async def list_ai_models(
    payload: AIModelListRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> AIModelListResponse:
    """Only Ollama exposes a real "what's actually installed" list - OpenAI/
    Anthropic/Moondream use the app's static curated picker instead (see
    frontend's aiProviderCatalog.ts)."""
    if payload.provider not in _OLLAMA_KINDS:
        return AIModelListResponse(
            ok=False, detail="Fetching a model list isn't supported for this provider."
        )
    api_key = await _resolve_saved_api_key(session, payload.tier, payload.api_key)
    default_url = (
        DEFAULT_OLLAMA_CLOUD_URL
        if payload.provider is AIProviderKind.OLLAMA_CLOUD
        else DEFAULT_OLLAMA_LOCAL_URL
    )
    provider = OllamaProvider(model="", base_url=payload.base_url or default_url, api_key=api_key)
    try:
        models = await provider.list_models()
    except AIProviderError as exc:
        return AIModelListResponse(ok=False, detail=str(exc))
    return AIModelListResponse(ok=True, models=models)
