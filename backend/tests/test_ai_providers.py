"""app/ai/providers.py: one interface, four backends, faked at each SDK's
own client boundary — never a real network call, matching the blinkpy
FakeAuth/FakeBlink convention used elsewhere in this project."""

# White-box: exercises _parse_entities directly to cover its edge cases
# without going through a full provider response.
# pyright: reportPrivateUsage=false

import json
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import httpx
import pytest

from app.ai.models import AIProviderKind
from app.ai.providers import (
    AIProviderError,
    AnalysisRequest,
    AnthropicProvider,
    MoondreamProvider,
    OllamaProvider,
    OpenAIProvider,
    _parse_entities,
    build_prompt,
    build_provider,
)

VALID_RESULT = {
    "summary": "A person walks up the driveway and leaves a package.",
    "suspicion_score": 0.1,
    "entities": [
        {
            "type": "person",
            "label": "delivery driver",
            "confidence": 0.9,
            "bbox": [0.1, 0.2, 0.3, 0.4],
        },
        {"type": "package", "label": "box", "confidence": 0.8, "bbox": None},
    ],
}


def make_request(**overrides: object) -> AnalysisRequest:
    defaults: dict[str, object] = {"images": [b"fake-jpeg-bytes"]}
    defaults.update(overrides)
    return AnalysisRequest(**defaults)  # type: ignore[arg-type]


# --------------------------------------------------------------- build_prompt


def test_build_prompt_includes_only_whats_provided() -> None:
    bare = build_prompt(make_request())
    assert "context" not in bare.lower().split("respond")[0] or "camera's context" not in bare

    full = build_prompt(
        make_request(
            camera_context="watches the driveway",
            baseline_context="usually sees a mail carrier around 2pm",
            feedback_examples=["a parked car at night was marked not suspicious"],
            detect_people_for_proximity=True,
            prior_tier_summary="a person lingered near the door (preliminary suspicion: 0.70)",
        )
    )
    assert "watches the driveway" in full
    assert "usually sees a mail carrier" in full
    assert "parked car at night" in full
    assert "tight bounding box" in full
    assert "a person lingered near the door" in full


def test_build_prompt_names_the_protected_vehicle_when_known() -> None:
    generic = build_prompt(make_request(detect_people_for_proximity=True))
    assert "(a vehicle)" in generic

    named = build_prompt(
        make_request(detect_people_for_proximity=True, vehicle_description="Blue Honda Civic")
    )
    assert "(a Blue Honda Civic)" in named
    assert "tell it apart from any other vehicle" in named


# ------------------------------------------------------------- _parse_entities


def test_parse_entities_handles_bbox_and_missing_fields() -> None:
    entities = _parse_entities(
        [
            {"type": "person", "confidence": 0.5, "label": "someone", "bbox": [0.0, 0.0, 1.0, 1.0]},
            {},
        ]
    )
    assert entities[0].bbox == (0.0, 0.0, 1.0, 1.0)
    assert entities[1].type == "unknown"
    assert entities[1].bbox is None


# ----------------------------------------------------------------- OpenAI


def _openai_response(content: str | None, usage: SimpleNamespace | None) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))], usage=usage
    )


async def test_openai_analyze_returns_parsed_result() -> None:
    provider = OpenAIProvider("gpt-5-nano", api_key="sk-test")
    provider._client.chat.completions.create = AsyncMock(  # type: ignore[method-assign]
        return_value=_openai_response(
            json.dumps(VALID_RESULT), SimpleNamespace(prompt_tokens=100, completion_tokens=20)
        )
    )
    result = await provider.analyze(make_request())
    assert result.summary == VALID_RESULT["summary"]
    assert result.suspicion_score == 0.1
    assert len(result.entities) == 2
    assert result.input_tokens == 100
    assert result.output_tokens == 20


async def test_openai_analyze_handles_missing_usage() -> None:
    provider = OpenAIProvider("gpt-5-nano", api_key="sk-test")
    provider._client.chat.completions.create = AsyncMock(  # type: ignore[method-assign]
        return_value=_openai_response(json.dumps(VALID_RESULT), None)
    )
    result = await provider.analyze(make_request())
    assert result.input_tokens == 0
    assert result.output_tokens == 0


async def test_openai_analyze_raises_on_empty_content() -> None:
    provider = OpenAIProvider("gpt-5-nano", api_key="sk-test")
    provider._client.chat.completions.create = AsyncMock(  # type: ignore[method-assign]
        return_value=_openai_response(None, None)
    )
    with pytest.raises(AIProviderError, match="empty response"):
        await provider.analyze(make_request())


async def test_openai_analyze_raises_on_unparseable_json() -> None:
    provider = OpenAIProvider("gpt-5-nano", api_key="sk-test")
    provider._client.chat.completions.create = AsyncMock(  # type: ignore[method-assign]
        return_value=_openai_response("not json", None)
    )
    with pytest.raises(AIProviderError, match="unparseable JSON"):
        await provider.analyze(make_request())


async def test_openai_analyze_wraps_sdk_errors() -> None:
    provider = OpenAIProvider("gpt-5-nano", api_key="sk-test")
    provider._client.chat.completions.create = AsyncMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]
    with pytest.raises(AIProviderError, match="OpenAI request failed"):
        await provider.analyze(make_request())


async def test_openai_test_connection_success_and_failure() -> None:
    provider = OpenAIProvider("gpt-5-nano", api_key="sk-test")
    provider._client.models.list = AsyncMock(return_value=None)  # type: ignore[method-assign]
    await provider.test_connection()

    provider._client.models.list = AsyncMock(side_effect=RuntimeError("bad key"))  # type: ignore[method-assign]
    with pytest.raises(AIProviderError, match="Could not reach OpenAI"):
        await provider.test_connection()


# --------------------------------------------------------------- Anthropic


def _anthropic_response(content: list[SimpleNamespace], usage: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(content=content, usage=usage)


async def test_anthropic_analyze_returns_parsed_result() -> None:
    provider = AnthropicProvider("claude-haiku", api_key="sk-ant-test")
    tool_use = SimpleNamespace(type="tool_use", input=VALID_RESULT)
    usage = SimpleNamespace(input_tokens=50, output_tokens=10)
    provider._client.messages.create = AsyncMock(  # type: ignore[method-assign]
        return_value=_anthropic_response([tool_use], usage)
    )
    result = await provider.analyze(make_request())
    assert result.summary == VALID_RESULT["summary"]
    assert result.input_tokens == 50
    assert result.output_tokens == 10


async def test_anthropic_analyze_raises_when_no_tool_use_block() -> None:
    provider = AnthropicProvider("claude-haiku", api_key="sk-ant-test")
    text_block = SimpleNamespace(type="text", text="I didn't use the tool.")
    usage = SimpleNamespace(input_tokens=1, output_tokens=1)
    provider._client.messages.create = AsyncMock(  # type: ignore[method-assign]
        return_value=_anthropic_response([text_block], usage)
    )
    with pytest.raises(AIProviderError, match="expected tool call"):
        await provider.analyze(make_request())


async def test_anthropic_analyze_wraps_sdk_errors() -> None:
    provider = AnthropicProvider("claude-haiku", api_key="sk-ant-test")
    provider._client.messages.create = AsyncMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]
    with pytest.raises(AIProviderError, match="Anthropic request failed"):
        await provider.analyze(make_request())


async def test_anthropic_test_connection_success_and_failure() -> None:
    provider = AnthropicProvider("claude-haiku", api_key="sk-ant-test")
    provider._client.models.list = AsyncMock(return_value=None)  # type: ignore[method-assign]
    await provider.test_connection()

    provider._client.models.list = AsyncMock(side_effect=RuntimeError("bad key"))  # type: ignore[method-assign]
    with pytest.raises(AIProviderError, match="Could not reach Anthropic"):
        await provider.test_connection()


# ------------------------------------------------------------------ Ollama


def _ollama_response(
    content: str | None, prompt_eval: int | None, eval_count: int | None
) -> SimpleNamespace:
    return SimpleNamespace(
        message=SimpleNamespace(content=content),
        prompt_eval_count=prompt_eval,
        eval_count=eval_count,
    )


async def test_ollama_analyze_returns_parsed_result() -> None:
    provider = OllamaProvider("llama3.2-vision", "http://localhost:11434")
    provider._client.chat = AsyncMock(  # type: ignore[method-assign]
        return_value=_ollama_response(json.dumps(VALID_RESULT), 80, 15)
    )
    result = await provider.analyze(make_request())
    assert result.summary == VALID_RESULT["summary"]
    assert result.input_tokens == 80
    assert result.output_tokens == 15


async def test_ollama_analyze_handles_missing_counts() -> None:
    provider = OllamaProvider("llama3.2-vision", "http://localhost:11434")
    provider._client.chat = AsyncMock(  # type: ignore[method-assign]
        return_value=_ollama_response(json.dumps(VALID_RESULT), None, None)
    )
    result = await provider.analyze(make_request())
    assert result.input_tokens == 0
    assert result.output_tokens == 0


async def test_ollama_analyze_raises_on_empty_content() -> None:
    provider = OllamaProvider("llama3.2-vision", "http://localhost:11434")
    provider._client.chat = AsyncMock(return_value=_ollama_response(None, 1, 1))  # type: ignore[method-assign]
    with pytest.raises(AIProviderError, match="empty response"):
        await provider.analyze(make_request())


async def test_ollama_analyze_raises_on_unparseable_json() -> None:
    provider = OllamaProvider("llama3.2-vision", "http://localhost:11434")
    provider._client.chat = AsyncMock(return_value=_ollama_response("nope", 1, 1))  # type: ignore[method-assign]
    with pytest.raises(AIProviderError, match="unparseable JSON"):
        await provider.analyze(make_request())


async def test_ollama_analyze_wraps_client_errors() -> None:
    provider = OllamaProvider("llama3.2-vision", "http://localhost:11434")
    provider._client.chat = AsyncMock(side_effect=RuntimeError("connection refused"))  # type: ignore[method-assign]
    with pytest.raises(AIProviderError, match="Ollama request failed"):
        await provider.analyze(make_request())


async def test_ollama_test_connection_success_and_failure() -> None:
    provider = OllamaProvider("llama3.2-vision", "http://localhost:11434")
    provider._client.list = AsyncMock(return_value=None)  # type: ignore[method-assign]
    await provider.test_connection()

    provider._client.list = AsyncMock(side_effect=RuntimeError("down"))  # type: ignore[method-assign]
    with pytest.raises(AIProviderError, match="Could not reach Ollama"):
        await provider.test_connection()


# ---------------------------------------------------------------- Moondream


def _moondream_transport(handler: object) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]


async def test_moondream_analyze_parses_structured_answer() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "answer": json.dumps(VALID_RESULT),
                "metrics": {"input_tokens": 30, "output_tokens": 5},
            },
        )

    provider = MoondreamProvider(
        "moondream3", "http://localhost:2020/v1", client=_moondream_transport(handler)
    )
    result = await provider.analyze(make_request())
    assert result.summary == VALID_RESULT["summary"]
    assert result.input_tokens == 30
    assert result.output_tokens == 5


async def test_moondream_analyze_degrades_gracefully_on_unstructured_answer() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"answer": "A person is at the door."})

    provider = MoondreamProvider(
        "moondream3", "http://localhost:2020/v1", client=_moondream_transport(handler)
    )
    result = await provider.analyze(make_request())
    assert result.summary == "A person is at the door."
    assert result.suspicion_score == 0.0
    assert result.entities == []
    assert result.input_tokens == 0


async def test_moondream_analyze_falls_back_when_answer_is_missing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    provider = MoondreamProvider(
        "moondream3", "http://localhost:2020/v1", client=_moondream_transport(handler)
    )
    result = await provider.analyze(make_request())
    assert "did not return a usable description" in result.summary


async def test_moondream_analyze_uses_the_middle_keyframe() -> None:
    seen_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"answer": json.dumps(VALID_RESULT)})

    provider = MoondreamProvider(
        "moondream3", "http://localhost:2020/v1", client=_moondream_transport(handler)
    )
    await provider.analyze(make_request(images=[b"first", b"middle", b"last"]))
    assert "bWlkZGxl" in str(seen_payloads[0]["image_url"])  # base64("middle")


async def test_moondream_analyze_requires_at_least_one_image() -> None:
    provider = MoondreamProvider("moondream3", "http://localhost:2020/v1")
    with pytest.raises(AIProviderError, match="No keyframes"):
        await provider.analyze(make_request(images=[]))


async def test_moondream_analyze_wraps_http_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    provider = MoondreamProvider(
        "moondream3", "http://localhost:2020/v1", client=_moondream_transport(handler)
    )
    with pytest.raises(AIProviderError, match="Moondream request failed"):
        await provider.analyze(make_request())


async def test_moondream_sends_auth_header_only_when_api_key_set() -> None:
    seen_headers: list[httpx.Headers] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.append(request.headers)
        return httpx.Response(200, json={"answer": json.dumps(VALID_RESULT)})

    local = MoondreamProvider("m", "http://localhost:2020/v1", client=_moondream_transport(handler))
    await local.analyze(make_request())
    assert "x-moondream-auth" not in seen_headers[0]

    cloud = MoondreamProvider(
        "m", "https://api.moondream.ai/v1", api_key="key-123", client=_moondream_transport(handler)
    )
    await cloud.analyze(make_request())
    assert seen_headers[1]["x-moondream-auth"] == "key-123"


async def test_moondream_test_connection_success_and_failure() -> None:
    def ok(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"answer": "ok"})

    provider = MoondreamProvider("m", "http://localhost:2020/v1", client=_moondream_transport(ok))
    await provider.test_connection()

    def fail(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    with pytest.raises(AIProviderError, match="Could not reach Moondream"):
        await MoondreamProvider(
            "m", "http://localhost:2020/v1", client=_moondream_transport(fail)
        ).test_connection()


# --------------------------------------------------------------- build_provider


def test_build_provider_openai_requires_api_key() -> None:
    with pytest.raises(AIProviderError, match="OpenAI requires"):
        build_provider(AIProviderKind.OPENAI, "gpt-5-nano", None, None)
    provider = build_provider(AIProviderKind.OPENAI, "gpt-5-nano", "sk-x", None)
    assert isinstance(provider, OpenAIProvider)


def test_build_provider_anthropic_requires_api_key() -> None:
    with pytest.raises(AIProviderError, match="Anthropic requires"):
        build_provider(AIProviderKind.ANTHROPIC, "claude-haiku", None, None)
    provider = build_provider(AIProviderKind.ANTHROPIC, "claude-haiku", "sk-ant", None)
    assert isinstance(provider, AnthropicProvider)


def test_build_provider_ollama_local_needs_no_key() -> None:
    provider = build_provider(AIProviderKind.OLLAMA, "llama3.2-vision", None, None)
    assert isinstance(provider, OllamaProvider)


def test_build_provider_ollama_cloud_requires_api_key() -> None:
    with pytest.raises(AIProviderError, match="Ollama Cloud requires"):
        build_provider(AIProviderKind.OLLAMA_CLOUD, "gpt-oss", None, None)
    provider = build_provider(AIProviderKind.OLLAMA_CLOUD, "gpt-oss", "key", None)
    assert isinstance(provider, OllamaProvider)


def test_build_provider_moondream_local_needs_no_key() -> None:
    provider = build_provider(AIProviderKind.MOONDREAM, "moondream3", None, None)
    assert isinstance(provider, MoondreamProvider)


def test_build_provider_moondream_cloud_requires_api_key() -> None:
    with pytest.raises(AIProviderError, match="Moondream Cloud requires"):
        build_provider(AIProviderKind.MOONDREAM_CLOUD, "moondream3", None, None)
    provider = build_provider(AIProviderKind.MOONDREAM_CLOUD, "moondream3", "key", None)
    assert isinstance(provider, MoondreamProvider)


def test_build_provider_rejects_an_unsupported_kind() -> None:
    # AIProviderKind is a closed StrEnum with six members, all handled above;
    # this exercises the defensive fallback for a value that bypasses the
    # enum (e.g. stale data), which `is` comparisons against real members
    # can never reach in practice.
    with pytest.raises(AIProviderError, match="Unsupported provider"):
        build_provider(cast("AIProviderKind", "bogus"), "model", None, None)


def test_build_provider_honors_custom_base_urls() -> None:
    provider = build_provider(
        AIProviderKind.OLLAMA, "llama3.2-vision", None, "http://gpu-box:11434"
    )
    assert isinstance(provider, OllamaProvider)
