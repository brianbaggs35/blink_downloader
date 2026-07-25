"""Singleton ai_settings row: get-or-create and the tri-state key update."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import SINGLETON_ID, AIProviderKind
from app.ai.schemas import AISettingsUpdate
from app.ai.service import get_ai_settings, update_ai_settings
from app.config import get_settings


async def test_get_ai_settings_creates_the_row_on_first_read(app_session: AsyncSession) -> None:
    row = await get_ai_settings(app_session)
    assert row.id == SINGLETON_ID
    assert row.enabled is False
    assert row.tier1_provider is None
    assert row.keyframes_per_clip == 4


async def test_get_ai_settings_is_idempotent(app_session: AsyncSession) -> None:
    first = await get_ai_settings(app_session)
    await app_session.commit()
    second = await get_ai_settings(app_session)
    assert first.id == second.id


async def test_update_sets_provider_config_and_encrypts_the_key(
    app_session: AsyncSession,
) -> None:
    payload = AISettingsUpdate(
        enabled=True,
        tier1_provider=AIProviderKind.OPENAI,
        tier1_model="gpt-5-nano",
        tier1_api_key="sk-super-secret",
        keyframes_per_clip=6,
        tier2_suspicion_threshold=0.7,
    )
    row = await update_ai_settings(app_session, payload, get_settings().encryption_key)
    assert row.enabled is True
    assert row.tier1_provider == AIProviderKind.OPENAI
    assert row.tier1_model == "gpt-5-nano"
    assert row.keyframes_per_clip == 6
    assert row.tier2_suspicion_threshold == 0.7
    assert row.tier1_encrypted_api_key is not None
    assert row.tier1_encrypted_api_key != "sk-super-secret"  # never stored in plaintext


async def test_update_with_none_key_leaves_existing_key_untouched(
    app_session: AsyncSession,
) -> None:
    encryption_key = get_settings().encryption_key
    first = AISettingsUpdate(
        enabled=True,
        tier1_provider=AIProviderKind.OPENAI,
        tier1_model="gpt-5-nano",
        tier1_api_key="sk-original",
    )
    row = await update_ai_settings(app_session, first, encryption_key)
    original_encrypted = row.tier1_encrypted_api_key

    second = AISettingsUpdate(
        enabled=True,
        tier1_provider=AIProviderKind.OPENAI,
        tier1_model="gpt-5-mini",  # only the model changes
        tier1_api_key=None,
    )
    row = await update_ai_settings(app_session, second, encryption_key)
    assert row.tier1_model == "gpt-5-mini"
    assert row.tier1_encrypted_api_key == original_encrypted


async def test_update_with_empty_string_key_clears_it(app_session: AsyncSession) -> None:
    encryption_key = get_settings().encryption_key
    first = AISettingsUpdate(
        enabled=True,
        tier1_provider=AIProviderKind.OPENAI,
        tier1_model="gpt-5-nano",
        tier1_api_key="sk-original",
    )
    await update_ai_settings(app_session, first, encryption_key)

    second = AISettingsUpdate(
        enabled=True,
        tier1_provider=AIProviderKind.OPENAI,
        tier1_model="gpt-5-nano",
        tier1_api_key="",
    )
    row = await update_ai_settings(app_session, second, encryption_key)
    assert row.tier1_encrypted_api_key is None


async def test_update_applies_to_tier2_independently(app_session: AsyncSession) -> None:
    encryption_key = get_settings().encryption_key
    payload = AISettingsUpdate(
        enabled=True,
        tier1_provider=AIProviderKind.OPENAI,
        tier1_model="gpt-5-nano",
        tier2_enabled=True,
        tier2_provider=AIProviderKind.ANTHROPIC,
        tier2_model="claude-sonnet-5",
        tier2_api_key="sk-ant-secret",
        tier2_base_url="https://api.anthropic.com",
    )
    row = await update_ai_settings(app_session, payload, encryption_key)
    assert row.tier2_provider == AIProviderKind.ANTHROPIC
    assert row.tier2_model == "claude-sonnet-5"
    assert row.tier2_base_url == "https://api.anthropic.com"
    assert row.tier2_encrypted_api_key is not None
