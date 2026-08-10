"""Storage integration settings CRUD (tri-state secrets, same pattern as
app.alerts.service), OAuth state handling, and per-provider client
construction (only built once every required field is present)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.blink.models import StorageBackend
from app.config import get_settings
from app.integrations.cloud import GoogleDriveClient, OneDriveClient, S3Client
from app.integrations.models import SINGLETON_ID, StorageIntegrationSettings
from app.integrations.schemas import StorageIntegrationSettingsUpdate
from app.integrations.service import (
    begin_oauth,
    build_google_drive_client,
    build_onedrive_client,
    build_s3_client,
    consume_oauth_state,
    get_storage_integration_settings,
    set_google_drive_refresh_token,
    set_onedrive_refresh_token,
    set_pending_oauth_code_verifier,
    update_storage_integration_settings,
)


async def test_get_creates_the_row_on_first_read(app_session: AsyncSession) -> None:
    row = await get_storage_integration_settings(app_session)
    assert row.id == SINGLETON_ID
    assert row.s3_enabled is False
    assert row.google_drive_enabled is False
    assert row.onedrive_enabled is False
    assert row.auto_archive_backend == StorageBackend.LOCAL
    assert row.auto_archive_after_days == 0


async def test_update_sets_the_auto_archive_backend(app_session: AsyncSession) -> None:
    payload = StorageIntegrationSettingsUpdate(auto_archive_backend=StorageBackend.S3)
    row = await update_storage_integration_settings(
        app_session, payload, get_settings().encryption_key
    )
    assert row.auto_archive_backend == StorageBackend.S3


async def test_update_sets_the_auto_archive_delay(app_session: AsyncSession) -> None:
    payload = StorageIntegrationSettingsUpdate(auto_archive_after_days=30)
    row = await update_storage_integration_settings(
        app_session, payload, get_settings().encryption_key
    )
    assert row.auto_archive_after_days == 30


async def test_update_sets_fields_and_encrypts_secrets(app_session: AsyncSession) -> None:
    payload = StorageIntegrationSettingsUpdate(
        s3_enabled=True,
        s3_bucket="my-bucket",
        s3_region="us-east-1",
        s3_access_key_id="AKIA123",
        s3_secret_access_key="super-secret",
        google_drive_enabled=True,
        google_drive_client_id="gd-client",
        google_drive_client_secret="gd-secret",
        onedrive_enabled=True,
        onedrive_client_id="od-client",
        onedrive_client_secret="od-secret",
    )
    row = await update_storage_integration_settings(
        app_session, payload, get_settings().encryption_key
    )
    assert row.s3_bucket == "my-bucket"
    assert row.encrypted_s3_access_key_id is not None
    assert row.encrypted_s3_access_key_id != "AKIA123"
    assert row.encrypted_s3_secret_access_key is not None
    assert row.encrypted_s3_secret_access_key != "super-secret"
    assert row.encrypted_google_drive_client_secret is not None
    assert row.encrypted_onedrive_client_secret is not None


async def test_update_with_none_secret_leaves_it_untouched(app_session: AsyncSession) -> None:
    encryption_key = get_settings().encryption_key
    first = StorageIntegrationSettingsUpdate(
        s3_enabled=True, s3_bucket="b", s3_access_key_id="original-key"
    )
    row = await update_storage_integration_settings(app_session, first, encryption_key)
    original = row.encrypted_s3_access_key_id

    second = StorageIntegrationSettingsUpdate(s3_enabled=True, s3_bucket="b", s3_access_key_id=None)
    row = await update_storage_integration_settings(app_session, second, encryption_key)
    assert row.encrypted_s3_access_key_id == original


async def test_update_with_empty_string_secret_clears_it(app_session: AsyncSession) -> None:
    encryption_key = get_settings().encryption_key
    first = StorageIntegrationSettingsUpdate(
        s3_enabled=True, s3_bucket="b", s3_access_key_id="original-key"
    )
    await update_storage_integration_settings(app_session, first, encryption_key)

    second = StorageIntegrationSettingsUpdate(s3_enabled=True, s3_bucket="b", s3_access_key_id="")
    row = await update_storage_integration_settings(app_session, second, encryption_key)
    assert row.encrypted_s3_access_key_id is None


# --------------------------------------------------------------- OAuth state


async def test_begin_oauth_sets_a_pending_state(app_session: AsyncSession) -> None:
    state = await begin_oauth(app_session, "google_drive")
    row = await get_storage_integration_settings(app_session)
    assert row.pending_oauth_provider == "google_drive"
    assert row.pending_oauth_state == state
    assert row.pending_oauth_code_verifier is None
    assert row.pending_oauth_expires_at is not None


async def test_begin_oauth_clears_a_stale_code_verifier_from_a_prior_flow(
    app_session: AsyncSession,
) -> None:
    """A restarted flow (e.g. the user clicks Connect again before
    finishing) must not let a previous attempt's verifier leak into the
    new one."""
    await begin_oauth(app_session, "google_drive")
    await set_pending_oauth_code_verifier(app_session, "stale-verifier")
    await begin_oauth(app_session, "google_drive")
    row = await get_storage_integration_settings(app_session)
    assert row.pending_oauth_code_verifier is None
    assert row.pending_oauth_expires_at is not None
    assert row.pending_oauth_expires_at > datetime.now(UTC)


async def test_consume_oauth_state_matches_and_clears(app_session: AsyncSession) -> None:
    state = await begin_oauth(app_session, "onedrive")
    assert await consume_oauth_state(app_session, "onedrive", state) == (True, None)
    row = await get_storage_integration_settings(app_session)
    assert row.pending_oauth_provider is None
    assert row.pending_oauth_state is None
    assert row.pending_oauth_code_verifier is None
    assert row.pending_oauth_expires_at is None


async def test_consume_oauth_state_returns_the_stored_code_verifier(
    app_session: AsyncSession,
) -> None:
    state = await begin_oauth(app_session, "google_drive")
    await set_pending_oauth_code_verifier(app_session, "verifier-abc")
    assert await consume_oauth_state(app_session, "google_drive", state) == (
        True,
        "verifier-abc",
    )


async def test_consume_oauth_state_clears_the_code_verifier_even_on_mismatch(
    app_session: AsyncSession,
) -> None:
    await begin_oauth(app_session, "google_drive")
    await set_pending_oauth_code_verifier(app_session, "verifier-abc")
    assert await consume_oauth_state(app_session, "google_drive", "not-the-real-state") == (
        False,
        None,
    )
    row = await get_storage_integration_settings(app_session)
    assert row.pending_oauth_code_verifier is None


async def test_consume_oauth_state_cannot_be_replayed(app_session: AsyncSession) -> None:
    state = await begin_oauth(app_session, "onedrive")
    assert await consume_oauth_state(app_session, "onedrive", state) == (True, None)
    assert await consume_oauth_state(app_session, "onedrive", state) == (False, None)


async def test_consume_oauth_state_rejects_wrong_provider(app_session: AsyncSession) -> None:
    state = await begin_oauth(app_session, "google_drive")
    assert await consume_oauth_state(app_session, "onedrive", state) == (False, None)


async def test_consume_oauth_state_rejects_wrong_state(app_session: AsyncSession) -> None:
    await begin_oauth(app_session, "google_drive")
    assert await consume_oauth_state(app_session, "google_drive", "not-the-real-state") == (
        False,
        None,
    )


async def test_consume_oauth_state_rejects_expired_state(app_session: AsyncSession) -> None:
    state = await begin_oauth(app_session, "google_drive")
    row = await get_storage_integration_settings(app_session)
    row.pending_oauth_expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await app_session.commit()
    assert await consume_oauth_state(app_session, "google_drive", state) == (False, None)


async def test_consume_oauth_state_with_nothing_pending(app_session: AsyncSession) -> None:
    assert await consume_oauth_state(app_session, "google_drive", "anything") == (False, None)


async def test_set_google_drive_refresh_token(app_session: AsyncSession) -> None:
    encryption_key = get_settings().encryption_key
    await set_google_drive_refresh_token(app_session, "rt-1", encryption_key)
    row = await get_storage_integration_settings(app_session)
    assert row.encrypted_google_drive_refresh_token is not None
    assert row.encrypted_google_drive_refresh_token != "rt-1"


async def test_set_onedrive_refresh_token(app_session: AsyncSession) -> None:
    encryption_key = get_settings().encryption_key
    await set_onedrive_refresh_token(app_session, "rt-2", encryption_key)
    row = await get_storage_integration_settings(app_session)
    assert row.encrypted_onedrive_refresh_token is not None
    assert row.encrypted_onedrive_refresh_token != "rt-2"


# --------------------------------------------------------------- client build


def _row(**overrides: object) -> StorageIntegrationSettings:
    return StorageIntegrationSettings(id=SINGLETON_ID, **overrides)  # type: ignore[arg-type]


def test_build_s3_client_none_when_disabled() -> None:
    row = _row(s3_enabled=False)
    assert build_s3_client(row, get_settings().encryption_key) is None


def test_build_s3_client_none_when_missing_credentials() -> None:
    row = _row(s3_enabled=True, s3_bucket="b", s3_region="us-east-1")
    assert build_s3_client(row, get_settings().encryption_key) is None


async def test_build_s3_client_when_fully_configured(app_session: AsyncSession) -> None:
    encryption_key = get_settings().encryption_key
    payload = StorageIntegrationSettingsUpdate(
        s3_enabled=True,
        s3_bucket="my-bucket",
        s3_region="us-east-1",
        s3_access_key_id="AKIA123",
        s3_secret_access_key="secret",
    )
    row = await update_storage_integration_settings(app_session, payload, encryption_key)
    client = build_s3_client(row, encryption_key)
    assert isinstance(client, S3Client)


async def test_build_google_drive_client_none_without_a_refresh_token(
    app_session: AsyncSession,
) -> None:
    encryption_key = get_settings().encryption_key
    payload = StorageIntegrationSettingsUpdate(
        google_drive_enabled=True,
        google_drive_client_id="gd-client",
        google_drive_client_secret="gd-secret",
    )
    row = await update_storage_integration_settings(app_session, payload, encryption_key)
    assert build_google_drive_client(row, encryption_key) is None


async def test_build_google_drive_client_when_fully_configured(
    app_session: AsyncSession,
) -> None:
    encryption_key = get_settings().encryption_key
    payload = StorageIntegrationSettingsUpdate(
        google_drive_enabled=True,
        google_drive_client_id="gd-client",
        google_drive_client_secret="gd-secret",
    )
    row = await update_storage_integration_settings(app_session, payload, encryption_key)
    await set_google_drive_refresh_token(app_session, "rt-1", encryption_key)
    row = await get_storage_integration_settings(app_session)
    client = build_google_drive_client(row, encryption_key)
    assert isinstance(client, GoogleDriveClient)


async def test_build_onedrive_client_none_without_a_refresh_token(
    app_session: AsyncSession,
) -> None:
    encryption_key = get_settings().encryption_key
    payload = StorageIntegrationSettingsUpdate(
        onedrive_enabled=True, onedrive_client_id="od-client", onedrive_client_secret="od-secret"
    )
    row = await update_storage_integration_settings(app_session, payload, encryption_key)
    assert build_onedrive_client(row, encryption_key) is None


async def test_build_onedrive_client_when_fully_configured(app_session: AsyncSession) -> None:
    encryption_key = get_settings().encryption_key
    payload = StorageIntegrationSettingsUpdate(
        onedrive_enabled=True, onedrive_client_id="od-client", onedrive_client_secret="od-secret"
    )
    await update_storage_integration_settings(app_session, payload, encryption_key)
    await set_onedrive_refresh_token(app_session, "rt-2", encryption_key)
    row = await get_storage_integration_settings(app_session)
    client = build_onedrive_client(row, encryption_key)
    assert isinstance(client, OneDriveClient)
