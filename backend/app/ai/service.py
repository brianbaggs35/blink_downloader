"""Read/write access to the singleton ai_settings row.

Update semantics: the caller resends the whole form except API keys, which
are tri-state — ``None`` leaves the stored key untouched (the read side
never returns it, so the frontend has nothing to re-submit), an empty
string clears it, anything else replaces it (encrypted at rest).
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import SINGLETON_ID, AISettings
from app.ai.schemas import AISettingsUpdate
from app.security.crypto import SecretBox


async def get_ai_settings(session: AsyncSession) -> AISettings:
    row = await session.get(AISettings, SINGLETON_ID)
    if row is None:
        row = AISettings(id=SINGLETON_ID)
        session.add(row)
        await session.flush()
    return row


def _apply_api_key(row_key_attr: str, row: AISettings, box: SecretBox, value: str | None) -> None:
    if value is None:
        return
    setattr(row, row_key_attr, box.encrypt(value) if value else None)


async def update_ai_settings(
    session: AsyncSession, payload: AISettingsUpdate, encryption_key: str
) -> AISettings:
    row = await get_ai_settings(session)
    box = SecretBox(encryption_key)

    row.enabled = payload.enabled
    row.tier1_provider = payload.tier1_provider
    row.tier1_model = payload.tier1_model
    row.tier1_base_url = payload.tier1_base_url
    _apply_api_key("tier1_encrypted_api_key", row, box, payload.tier1_api_key)

    row.tier2_enabled = payload.tier2_enabled
    row.tier2_provider = payload.tier2_provider
    row.tier2_model = payload.tier2_model
    row.tier2_base_url = payload.tier2_base_url
    _apply_api_key("tier2_encrypted_api_key", row, box, payload.tier2_api_key)

    row.keyframes_per_clip = payload.keyframes_per_clip
    row.tier2_suspicion_threshold = payload.tier2_suspicion_threshold
    row.feedback_context_count = payload.feedback_context_count

    await session.commit()
    await session.refresh(row)
    return row
