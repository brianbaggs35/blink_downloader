"""Best-effort USD cost estimation for AI provider calls.

Provider pricing changes over time and none of the four providers expose a
live pricing API, so this is a small, hand-maintained table — not a billing
source of truth. Local providers (Ollama, Moondream, both self-hosted) are
genuinely free, so they always cost $0.00. A cloud model not in the table
logs once and reports $0.00 rather than guessing, matching this project's
policy of degrading honestly instead of pretending precision it doesn't have.
"""

from app.ai.models import AIProviderKind
from app.logs import get_logger

logger = get_logger(__name__)

#: USD per 1,000,000 tokens, (input, output). Update as providers reprice.
_PRICING_USD_PER_1M_TOKENS: dict[AIProviderKind, dict[str, tuple[float, float]]] = {
    AIProviderKind.OPENAI: {
        "gpt-5": (2.50, 10.00),
        "gpt-5-mini": (0.30, 2.00),
        "gpt-5-nano": (0.05, 0.40),
    },
    AIProviderKind.ANTHROPIC: {
        "claude-opus-5": (12.00, 60.00),
        "claude-sonnet-5": (3.00, 15.00),
        "claude-fable-5": (0.80, 4.00),
        "claude-haiku-4-5-20251001": (0.80, 4.00),
    },
    # Ollama Cloud and Moondream Cloud host a mix of open-weight models under
    # their own metered pricing; without a stable per-model table to draw on,
    # calls are logged with tokens/latency but cost is left at $0.00 until a
    # specific model is added below.
    AIProviderKind.OLLAMA_CLOUD: {},
    AIProviderKind.MOONDREAM_CLOUD: {},
}

_FREE_PROVIDERS = frozenset({AIProviderKind.OLLAMA, AIProviderKind.MOONDREAM})

_logged_unknown_models: set[tuple[AIProviderKind, str]] = set()


def estimate_cost_usd(
    provider: AIProviderKind, model: str, input_tokens: int, output_tokens: int
) -> float:
    if provider in _FREE_PROVIDERS:
        return 0.0

    rates = _PRICING_USD_PER_1M_TOKENS.get(provider, {}).get(model)
    if rates is None:
        if (provider, model) not in _logged_unknown_models:
            _logged_unknown_models.add((provider, model))
            logger.info("ai_pricing.unknown_model", provider=provider.value, model=model)
        return 0.0

    input_rate, output_rate = rates
    return round(input_tokens * input_rate / 1_000_000 + output_tokens * output_rate / 1_000_000, 6)
