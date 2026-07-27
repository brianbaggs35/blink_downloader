"""Storage integration settings CRUD, OAuth state handling, and client
construction (decrypting stored credentials just long enough to build a
provider client - see app.integrations.cloud)."""

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.cloud import GoogleDriveClient, OneDriveClient, S3Client
from app.integrations.models import SINGLETON_ID, StorageIntegrationSettings
from app.integrations.schemas import StorageIntegrationSettingsUpdate
from app.security.crypto import SecretBox

OAUTH_STATE_TTL_MINUTES = 10


async def get_storage_integration_settings(session: AsyncSession) -> StorageIntegrationSettings:
    row = await session.get(StorageIntegrationSettings, SINGLETON_ID)
    if row is None:
        row = StorageIntegrationSettings(id=SINGLETON_ID)
        session.add(row)
        await session.flush()
    return row


def _apply_secret(
    row: StorageIntegrationSettings, attr: str, box: SecretBox, value: str | None
) -> None:
    if value is None:
        return
    setattr(row, attr, box.encrypt(value) if value else None)


async def update_storage_integration_settings(
    session: AsyncSession, payload: StorageIntegrationSettingsUpdate, encryption_key: str
) -> StorageIntegrationSettings:
    row = await get_storage_integration_settings(session)
    box = SecretBox(encryption_key)

    row.s3_enabled = payload.s3_enabled
    row.s3_bucket = payload.s3_bucket
    row.s3_region = payload.s3_region
    row.s3_prefix = payload.s3_prefix
    _apply_secret(row, "encrypted_s3_access_key_id", box, payload.s3_access_key_id)
    _apply_secret(row, "encrypted_s3_secret_access_key", box, payload.s3_secret_access_key)

    row.google_drive_enabled = payload.google_drive_enabled
    row.google_drive_client_id = payload.google_drive_client_id
    _apply_secret(
        row,
        "encrypted_google_drive_client_secret",
        box,
        payload.google_drive_client_secret,
    )
    row.google_drive_folder_id = payload.google_drive_folder_id

    row.onedrive_enabled = payload.onedrive_enabled
    row.onedrive_client_id = payload.onedrive_client_id
    _apply_secret(row, "encrypted_onedrive_client_secret", box, payload.onedrive_client_secret)
    row.onedrive_folder_path = payload.onedrive_folder_path

    await session.commit()
    await session.refresh(row)
    return row


async def begin_oauth(session: AsyncSession, provider: str) -> str:
    """Starts (or restarts) an OAuth connect flow for `provider`, returning
    a fresh CSRF state token good for OAUTH_STATE_TTL_MINUTES."""
    row = await get_storage_integration_settings(session)
    state = secrets.token_urlsafe(32)
    row.pending_oauth_provider = provider
    row.pending_oauth_state = state
    row.pending_oauth_expires_at = datetime.now(UTC) + timedelta(minutes=OAUTH_STATE_TTL_MINUTES)
    await session.commit()
    return state


async def consume_oauth_state(session: AsyncSession, provider: str, state: str) -> bool:
    """True if `state` matches an unexpired, in-progress flow for
    `provider` - clears the pending state either way, so a state can never
    be replayed."""
    row = await get_storage_integration_settings(session)
    matches = (
        row.pending_oauth_provider == provider
        and row.pending_oauth_state is not None
        and secrets.compare_digest(row.pending_oauth_state, state)
        and row.pending_oauth_expires_at is not None
        and row.pending_oauth_expires_at > datetime.now(UTC)
    )
    row.pending_oauth_provider = None
    row.pending_oauth_state = None
    row.pending_oauth_expires_at = None
    await session.commit()
    return matches


async def set_google_drive_refresh_token(
    session: AsyncSession, refresh_token: str, encryption_key: str
) -> None:
    row = await get_storage_integration_settings(session)
    row.encrypted_google_drive_refresh_token = SecretBox(encryption_key).encrypt(refresh_token)
    await session.commit()


async def set_onedrive_refresh_token(
    session: AsyncSession, refresh_token: str, encryption_key: str
) -> None:
    row = await get_storage_integration_settings(session)
    row.encrypted_onedrive_refresh_token = SecretBox(encryption_key).encrypt(refresh_token)
    await session.commit()


def build_s3_client(row: StorageIntegrationSettings, encryption_key: str) -> S3Client | None:
    if not (
        row.s3_enabled
        and row.s3_bucket
        and row.s3_region
        and row.encrypted_s3_access_key_id
        and row.encrypted_s3_secret_access_key
    ):
        return None
    box = SecretBox(encryption_key)
    return S3Client(
        access_key_id=box.decrypt(row.encrypted_s3_access_key_id),
        secret_access_key=box.decrypt(row.encrypted_s3_secret_access_key),
        region=row.s3_region,
        bucket=row.s3_bucket,
        prefix=row.s3_prefix,
    )


def build_google_drive_client(
    row: StorageIntegrationSettings, encryption_key: str
) -> GoogleDriveClient | None:
    if not (
        row.google_drive_enabled
        and row.google_drive_client_id
        and row.encrypted_google_drive_client_secret
        and row.encrypted_google_drive_refresh_token
    ):
        return None
    box = SecretBox(encryption_key)
    return GoogleDriveClient(
        client_id=row.google_drive_client_id,
        client_secret=box.decrypt(row.encrypted_google_drive_client_secret),
        refresh_token=box.decrypt(row.encrypted_google_drive_refresh_token),
        folder_id=row.google_drive_folder_id,
    )


def build_onedrive_client(
    row: StorageIntegrationSettings, encryption_key: str
) -> OneDriveClient | None:
    if not (
        row.onedrive_enabled
        and row.onedrive_client_id
        and row.encrypted_onedrive_client_secret
        and row.encrypted_onedrive_refresh_token
    ):
        return None
    box = SecretBox(encryption_key)
    return OneDriveClient(
        client_id=row.onedrive_client_id,
        client_secret=box.decrypt(row.encrypted_onedrive_client_secret),
        refresh_token=box.decrypt(row.encrypted_onedrive_refresh_token),
        folder_path=row.onedrive_folder_path,
    )
