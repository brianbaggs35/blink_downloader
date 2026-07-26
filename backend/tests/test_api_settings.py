"""GET/PATCH /api/settings/storage and GET/PUT/test-connection /api/settings/ai.

test-connection's provider is faked (patched at the name imported into
app.api.settings), matching test_ai_providers.py's "never a real network
call" policy.
"""

# pytest calls autouse fixtures implicitly; pyright can't see that usage.
# pyright: reportUnusedFunction=false

from typing import ClassVar

import pytest
from httpx import AsyncClient

from app.ai.models import AIProviderKind
from app.ai.providers import AIProviderError, AnalysisRequest, AnalysisResult


async def test_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/settings/storage")
    assert response.status_code == 401


async def test_default_reflects_env_var(admin_client: AsyncClient) -> None:
    response = await admin_client.get("/api/settings/storage")
    assert response.status_code == 200
    body = response.json()
    assert body["is_default"] is True
    assert body["storage_dir"]


async def test_update_to_a_writable_directory(admin_client: AsyncClient, tmp_path: object) -> None:
    new_dir = str(tmp_path) + "/clips"
    response = await admin_client.patch("/api/settings/storage", json={"storage_dir": new_dir})
    assert response.status_code == 200
    body = response.json()
    assert body["storage_dir"] == new_dir
    assert body["is_default"] is False

    followup = await admin_client.get("/api/settings/storage")
    assert followup.json()["storage_dir"] == new_dir


async def test_clearing_the_override_restores_default(
    admin_client: AsyncClient, tmp_path: object
) -> None:
    await admin_client.patch("/api/settings/storage", json={"storage_dir": str(tmp_path)})
    response = await admin_client.patch("/api/settings/storage", json={"storage_dir": None})
    assert response.status_code == 200
    assert response.json()["is_default"] is True


async def test_relative_path_rejected_by_schema(admin_client: AsyncClient) -> None:
    response = await admin_client.patch(
        "/api/settings/storage", json={"storage_dir": "relative/path"}
    )
    assert response.status_code == 422


async def test_unwritable_path_rejected(admin_client: AsyncClient) -> None:
    response = await admin_client.patch(
        "/api/settings/storage", json={"storage_dir": "/proc/blink-cannot-write-here"}
    )
    assert response.status_code == 400
    assert "not exist or is not writable" in response.json()["detail"]


# ------------------------------------------------------------- AI settings


async def test_ai_get_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/settings/ai")
    assert response.status_code == 401


async def test_ai_get_requires_admin(viewer_client: AsyncClient) -> None:
    response = await viewer_client.get("/api/settings/ai")
    assert response.status_code == 403


async def test_ai_get_defaults(admin_client: AsyncClient) -> None:
    response = await admin_client.get("/api/settings/ai")
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    assert body["tier1_provider"] is None
    assert body["tier1_api_key_set"] is False
    assert body["keyframes_per_clip"] == 4


async def test_ai_put_updates_fields_and_never_echoes_the_key(admin_client: AsyncClient) -> None:
    response = await admin_client.put(
        "/api/settings/ai",
        json={
            "enabled": True,
            "tier1_provider": "openai",
            "tier1_model": "gpt-5-nano",
            "tier1_api_key": "sk-super-secret-value",
            "keyframes_per_clip": 6,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["tier1_provider"] == "openai"
    assert body["tier1_api_key_set"] is True
    assert body["keyframes_per_clip"] == 6
    assert "sk-super-secret-value" not in response.text

    followup = await admin_client.get("/api/settings/ai")
    assert followup.json()["tier1_api_key_set"] is True
    assert "sk-super-secret-value" not in followup.text


async def test_ai_put_omitting_key_leaves_it_set(admin_client: AsyncClient) -> None:
    await admin_client.put(
        "/api/settings/ai",
        json={
            "enabled": True,
            "tier1_provider": "openai",
            "tier1_model": "gpt-5-nano",
            "tier1_api_key": "sk-original",
        },
    )
    response = await admin_client.put(
        "/api/settings/ai",
        json={"enabled": True, "tier1_provider": "openai", "tier1_model": "gpt-5-mini"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["tier1_model"] == "gpt-5-mini"
    assert body["tier1_api_key_set"] is True  # untouched, not cleared


async def test_ai_put_rejects_out_of_range_keyframes(admin_client: AsyncClient) -> None:
    response = await admin_client.put(
        "/api/settings/ai", json={"enabled": False, "keyframes_per_clip": 0}
    )
    assert response.status_code == 422


async def test_ai_put_requires_admin(viewer_client: AsyncClient) -> None:
    response = await viewer_client.put("/api/settings/ai", json={"enabled": True})
    assert response.status_code == 403


class FakeConnectionProvider:
    received_api_key: ClassVar[str | None] = None
    should_fail: ClassVar[bool] = False

    def __init__(self, model: str, api_key: str | None, base_url: str | None) -> None:
        del model, base_url
        FakeConnectionProvider.received_api_key = api_key

    async def test_connection(self) -> None:
        if FakeConnectionProvider.should_fail:
            raise AIProviderError("could not reach the provider")

    async def analyze(self, request: AnalysisRequest) -> AnalysisResult:
        del request
        if FakeConnectionProvider.should_fail:
            raise AIProviderError("could not reach the provider")
        return AnalysisResult(
            summary="Nothing notable.",
            suspicion_score=0.05,
            entities=[],
            input_tokens=1,
            output_tokens=1,
        )


def _fake_build_provider(
    _kind: AIProviderKind, model: str, api_key: str | None, base_url: str | None
) -> FakeConnectionProvider:
    return FakeConnectionProvider(model, api_key, base_url)


@pytest.fixture(autouse=True)
def _reset_fake_connection_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeConnectionProvider.received_api_key = None
    FakeConnectionProvider.should_fail = False
    monkeypatch.setattr("app.api.settings.build_provider", _fake_build_provider)


async def test_ai_test_connection_requires_admin(viewer_client: AsyncClient) -> None:
    response = await viewer_client.post(
        "/api/settings/ai/test-connection",
        json={"tier": "tier1", "provider": "openai", "model": "gpt-5-nano", "api_key": "sk-x"},
    )
    assert response.status_code == 403


async def test_ai_test_connection_success(admin_client: AsyncClient) -> None:
    response = await admin_client.post(
        "/api/settings/ai/test-connection",
        json={"tier": "tier1", "provider": "openai", "model": "gpt-5-nano", "api_key": "sk-x"},
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True, "detail": None}
    assert FakeConnectionProvider.received_api_key == "sk-x"


async def test_ai_test_connection_reports_failure_without_a_500(admin_client: AsyncClient) -> None:
    FakeConnectionProvider.should_fail = True
    response = await admin_client.post(
        "/api/settings/ai/test-connection",
        json={"tier": "tier1", "provider": "openai", "model": "gpt-5-nano", "api_key": "sk-x"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert "could not reach" in body["detail"]


async def test_ai_test_connection_falls_back_to_the_saved_key_when_omitted(
    admin_client: AsyncClient,
) -> None:
    await admin_client.put(
        "/api/settings/ai",
        json={
            "enabled": True,
            "tier1_provider": AIProviderKind.OPENAI.value,
            "tier1_model": "gpt-5-nano",
            "tier1_api_key": "sk-saved-key",
        },
    )
    response = await admin_client.post(
        "/api/settings/ai/test-connection",
        json={"tier": "tier1", "provider": "openai", "model": "gpt-5-nano"},
    )
    assert response.status_code == 200
    assert FakeConnectionProvider.received_api_key == "sk-saved-key"


async def test_ai_test_connection_tier2_uses_tier2_saved_key(admin_client: AsyncClient) -> None:
    await admin_client.put(
        "/api/settings/ai",
        json={
            "enabled": True,
            "tier1_provider": "openai",
            "tier1_model": "gpt-5-nano",
            "tier2_enabled": True,
            "tier2_provider": "anthropic",
            "tier2_model": "claude-sonnet-5",
            "tier2_api_key": "sk-ant-saved",
        },
    )
    response = await admin_client.post(
        "/api/settings/ai/test-connection",
        json={"tier": "tier2", "provider": "anthropic", "model": "claude-sonnet-5"},
    )
    assert response.status_code == 200
    assert FakeConnectionProvider.received_api_key == "sk-ant-saved"


async def test_ai_test_connection_with_no_saved_key_uses_none(admin_client: AsyncClient) -> None:
    response = await admin_client.post(
        "/api/settings/ai/test-connection",
        json={"tier": "tier1", "provider": "ollama", "model": "llama3.2-vision"},
    )
    assert response.status_code == 200
    assert FakeConnectionProvider.received_api_key is None


# ------------------------------------------------------ AI test-analysis


async def test_ai_test_analysis_requires_admin(viewer_client: AsyncClient) -> None:
    response = await viewer_client.post(
        "/api/settings/ai/test-analysis",
        json={"tier": "tier1", "provider": "ollama", "model": "llava", "api_key": None},
    )
    assert response.status_code == 403


async def test_ai_test_analysis_success_reports_the_model_response(
    admin_client: AsyncClient,
) -> None:
    response = await admin_client.post(
        "/api/settings/ai/test-analysis",
        json={"tier": "tier1", "provider": "ollama", "model": "llava", "api_key": None},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert "Nothing notable." in body["detail"]
    assert "0.05" in body["detail"]


async def test_ai_test_analysis_reports_failure_without_a_500(admin_client: AsyncClient) -> None:
    FakeConnectionProvider.should_fail = True
    response = await admin_client.post(
        "/api/settings/ai/test-analysis",
        json={"tier": "tier1", "provider": "openai", "model": "gpt-5-nano", "api_key": "sk-x"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert "could not reach" in body["detail"]
