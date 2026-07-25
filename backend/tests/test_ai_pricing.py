"""Best-effort cost estimation: free for local providers, table lookup for
cloud providers, and an honest $0.00 (not a guess) for an unlisted model."""

from app.ai.models import AIProviderKind
from app.ai.pricing import estimate_cost_usd


def test_local_ollama_is_always_free() -> None:
    assert estimate_cost_usd(AIProviderKind.OLLAMA, "llama3.2-vision", 10_000, 5_000) == 0.0


def test_local_moondream_is_always_free() -> None:
    assert estimate_cost_usd(AIProviderKind.MOONDREAM, "moondream3", 10_000, 5_000) == 0.0


def test_known_openai_model_computes_expected_cost() -> None:
    # gpt-5-nano: $0.05 / $0.40 per 1M tokens (input / output).
    cost = estimate_cost_usd(AIProviderKind.OPENAI, "gpt-5-nano", 1_000_000, 1_000_000)
    assert cost == 0.45


def test_known_anthropic_model_computes_expected_cost() -> None:
    cost = estimate_cost_usd(AIProviderKind.ANTHROPIC, "claude-haiku-4-5-20251001", 500_000, 0)
    assert cost == 0.40


def test_zero_tokens_costs_nothing() -> None:
    assert estimate_cost_usd(AIProviderKind.OPENAI, "gpt-5-nano", 0, 0) == 0.0


def test_unknown_model_reports_zero_rather_than_guessing() -> None:
    cost = estimate_cost_usd(AIProviderKind.OPENAI, "some-future-model", 1_000_000, 1_000_000)
    assert cost == 0.0


def test_unlisted_cloud_provider_reports_zero() -> None:
    cost = estimate_cost_usd(AIProviderKind.OLLAMA_CLOUD, "gpt-oss:120b", 1_000_000, 1_000_000)
    assert cost == 0.0


def test_unknown_model_dedup_does_not_break_repeated_calls() -> None:
    # The same unknown (provider, model) pair is only logged once; calling
    # it repeatedly should just keep returning 0.0, never raise.
    assert estimate_cost_usd(AIProviderKind.ANTHROPIC, "claude-unreleased", 100, 100) == 0.0
    assert estimate_cost_usd(AIProviderKind.ANTHROPIC, "claude-unreleased", 100, 100) == 0.0
