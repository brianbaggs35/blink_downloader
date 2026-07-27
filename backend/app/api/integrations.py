"""Settings > Integrations: S3/Google Drive/OneDrive connection settings,
a combined test-connection endpoint, and the two providers' OAuth connect
flows (S3 uses static credentials - there's no OAuth dance for it).
"""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.integrations.cloud import (
    CloudStorageError,
    google_drive_authorize_url,
    google_drive_exchange_code,
    onedrive_authorize_url,
    onedrive_exchange_code,
)
from app.integrations.models import StorageIntegrationSettings
from app.integrations.schemas import (
    StorageIntegrationSettingsRead,
    StorageIntegrationSettingsUpdate,
    StorageTestResponse,
    StorageTestResult,
)
from app.integrations.service import (
    begin_oauth,
    build_google_drive_client,
    build_onedrive_client,
    build_s3_client,
    consume_oauth_state,
    get_storage_integration_settings,
    set_google_drive_refresh_token,
    set_onedrive_refresh_token,
    update_storage_integration_settings,
)
from app.logs import get_logger
from app.security.crypto import SecretBox
from app.users.auth import current_superuser

logger = get_logger(__name__)

router = APIRouter(prefix="/settings/storage-integrations", tags=["integrations"])

GOOGLE_DRIVE = "google_drive"
ONEDRIVE = "onedrive"

SETTINGS_REDIRECT_PATH = "/integrations"


def _read(row: StorageIntegrationSettings) -> StorageIntegrationSettingsRead:
    return StorageIntegrationSettingsRead(
        s3_enabled=row.s3_enabled,
        s3_bucket=row.s3_bucket,
        s3_region=row.s3_region,
        s3_prefix=row.s3_prefix,
        s3_credentials_set=bool(
            row.encrypted_s3_access_key_id and row.encrypted_s3_secret_access_key
        ),
        google_drive_enabled=row.google_drive_enabled,
        google_drive_client_id=row.google_drive_client_id,
        google_drive_client_secret_set=bool(row.encrypted_google_drive_client_secret),
        google_drive_connected=bool(row.encrypted_google_drive_refresh_token),
        google_drive_folder_id=row.google_drive_folder_id,
        onedrive_enabled=row.onedrive_enabled,
        onedrive_client_id=row.onedrive_client_id,
        onedrive_client_secret_set=bool(row.encrypted_onedrive_client_secret),
        onedrive_connected=bool(row.encrypted_onedrive_refresh_token),
        onedrive_folder_path=row.onedrive_folder_path,
        auto_archive_backend=row.auto_archive_backend,
    )


@router.get("", response_model=StorageIntegrationSettingsRead)
async def get_integration_settings(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> StorageIntegrationSettingsRead:
    return _read(await get_storage_integration_settings(session))


@router.put("", response_model=StorageIntegrationSettingsRead)
async def put_integration_settings(
    payload: StorageIntegrationSettingsUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> StorageIntegrationSettingsRead:
    row = await update_storage_integration_settings(session, payload, get_settings().encryption_key)
    logger.info("settings.storage_integrations_updated")
    return _read(row)


async def _try(action: Callable[[], Awaitable[None]]) -> StorageTestResult:
    try:
        await action()
    except CloudStorageError as exc:
        return StorageTestResult(ok=False, detail=str(exc))
    return StorageTestResult(ok=True, detail="Connected.")


@router.post("/test", response_model=StorageTestResponse)
async def test_integrations(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> StorageTestResponse:
    row = await get_storage_integration_settings(session)
    encryption_key = get_settings().encryption_key
    response = StorageTestResponse()

    s3_client = build_s3_client(row, encryption_key)
    if s3_client is not None:
        response.s3 = await _try(s3_client.test_connection)

    drive_client = build_google_drive_client(row, encryption_key)
    if drive_client is not None:
        response.google_drive = await _try(drive_client.test_connection)

    onedrive_client = build_onedrive_client(row, encryption_key)
    if onedrive_client is not None:
        response.onedrive = await _try(onedrive_client.test_connection)

    return response


@router.get("/google-drive/oauth/start")
async def start_google_drive_oauth(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> RedirectResponse:
    row = await get_storage_integration_settings(session)
    if not row.google_drive_client_id or not row.encrypted_google_drive_client_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Save a Google Drive client ID and secret before connecting.",
        )
    client_secret = SecretBox(get_settings().encryption_key).decrypt(
        row.encrypted_google_drive_client_secret
    )
    state = await begin_oauth(session, GOOGLE_DRIVE)
    redirect_uri = str(request.url_for("callback_google_drive_oauth"))
    authorize_url = google_drive_authorize_url(
        row.google_drive_client_id, client_secret, redirect_uri, state
    )
    return RedirectResponse(authorize_url, status_code=status.HTTP_302_FOUND)


@router.get("/google-drive/oauth/callback", name="callback_google_drive_oauth")
async def callback_google_drive_oauth(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
) -> RedirectResponse:
    if not code or not state or not await consume_oauth_state(session, GOOGLE_DRIVE, state):
        return RedirectResponse(f"{SETTINGS_REDIRECT_PATH}?error=google_drive")
    row = await get_storage_integration_settings(session)
    settings = get_settings()
    if not row.google_drive_client_id or not row.encrypted_google_drive_client_secret:
        return RedirectResponse(f"{SETTINGS_REDIRECT_PATH}?error=google_drive")
    client_secret = SecretBox(settings.encryption_key).decrypt(
        row.encrypted_google_drive_client_secret
    )
    redirect_uri = str(request.url_for("callback_google_drive_oauth"))
    try:
        refresh_token = await google_drive_exchange_code(
            row.google_drive_client_id, client_secret, redirect_uri, code
        )
    except CloudStorageError as exc:
        logger.warning("integrations.google_drive_oauth_failed", error=str(exc))
        return RedirectResponse(f"{SETTINGS_REDIRECT_PATH}?error=google_drive")
    await set_google_drive_refresh_token(session, refresh_token, settings.encryption_key)
    logger.info("integrations.google_drive_connected")
    return RedirectResponse(f"{SETTINGS_REDIRECT_PATH}?connected=google_drive")


@router.get("/onedrive/oauth/start")
async def start_onedrive_oauth(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[object, Depends(current_superuser)],
) -> RedirectResponse:
    row = await get_storage_integration_settings(session)
    if not row.onedrive_client_id or not row.encrypted_onedrive_client_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Save a OneDrive client ID and secret before connecting.",
        )
    client_secret = SecretBox(get_settings().encryption_key).decrypt(
        row.encrypted_onedrive_client_secret
    )
    state = await begin_oauth(session, ONEDRIVE)
    redirect_uri = str(request.url_for("callback_onedrive_oauth"))
    authorize_url = onedrive_authorize_url(
        row.onedrive_client_id, client_secret, redirect_uri, state
    )
    return RedirectResponse(authorize_url, status_code=status.HTTP_302_FOUND)


@router.get("/onedrive/oauth/callback", name="callback_onedrive_oauth")
async def callback_onedrive_oauth(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
) -> RedirectResponse:
    if not code or not state or not await consume_oauth_state(session, ONEDRIVE, state):
        return RedirectResponse(f"{SETTINGS_REDIRECT_PATH}?error=onedrive")
    row = await get_storage_integration_settings(session)
    settings = get_settings()
    if not row.onedrive_client_id or not row.encrypted_onedrive_client_secret:
        return RedirectResponse(f"{SETTINGS_REDIRECT_PATH}?error=onedrive")
    client_secret = SecretBox(settings.encryption_key).decrypt(row.encrypted_onedrive_client_secret)
    redirect_uri = str(request.url_for("callback_onedrive_oauth"))
    try:
        refresh_token = await onedrive_exchange_code(
            row.onedrive_client_id, client_secret, redirect_uri, code
        )
    except CloudStorageError as exc:
        logger.warning("integrations.onedrive_oauth_failed", error=str(exc))
        return RedirectResponse(f"{SETTINGS_REDIRECT_PATH}?error=onedrive")
    await set_onedrive_refresh_token(session, refresh_token, settings.encryption_key)
    logger.info("integrations.onedrive_connected")
    return RedirectResponse(f"{SETTINGS_REDIRECT_PATH}?connected=onedrive")
