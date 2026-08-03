import type { AIProviderKind } from "@/api";

/**
 * Cloud providers have a fixed, operator-hosted endpoint - a base URL field
 * is only meaningful for the self-hosted (local) providers, which run on
 * whatever host:port the operator points us at.
 */
export const CLOUD_PROVIDER_KINDS: ReadonlySet<AIProviderKind> = new Set([
  "openai",
  "anthropic",
  "ollama_cloud",
  "moondream_cloud",
]);

export function isCloudProvider(kind: AIProviderKind | null): boolean {
  return kind !== null && CLOUD_PROVIDER_KINDS.has(kind);
}

/** Only Ollama exposes a real "list what's installed" API - see the
 * backend's /settings/ai/list-models route. */
export const OLLAMA_PROVIDER_KINDS: ReadonlySet<AIProviderKind> = new Set([
  "ollama",
  "ollama_cloud",
]);

export function isOllamaProvider(kind: AIProviderKind | null): boolean {
  return kind !== null && OLLAMA_PROVIDER_KINDS.has(kind);
}

/**
 * Pre-populated model suggestions per provider, newest to oldest, offered
 * through an editable AutoComplete rather than a closed dropdown - Ollama
 * and Moondream are inherently open-ended (any locally pulled/served model
 * works), so the list is a typo-saving convenience there, never a hard
 * restriction. OpenAI/Anthropic entries are the real, current model IDs for
 * those providers as of this writing; keep this list in sync as new
 * generations ship.
 */
export const MODEL_SUGGESTIONS: Record<AIProviderKind, string[]> = {
  openai: [
    "gpt-5.6",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "gpt-5.4-mini",
    "gpt-5.4-nano",
    "gpt-5",
    "gpt-5-mini",
    "gpt-5-nano",
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-4.1-nano",
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4-turbo",
    "gpt-4",
  ],
  anthropic: ["claude-fable-5", "claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5-20251001"],
  ollama: [
    "qwen2.5vl",
    "llama3.2-vision",
    "minicpm-v",
    "llava-llama3",
    "llava",
    "bakllava",
    "moondream",
  ],
  ollama_cloud: [
    "qwen2.5vl",
    "llama3.2-vision",
    "minicpm-v",
    "llava-llama3",
    "llava",
    "bakllava",
    "moondream",
  ],
  moondream: ["moondream2", "moondream-2b", "moondream-0.5b"],
  moondream_cloud: ["moondream2", "moondream-2b", "moondream-0.5b"],
};

function filterList(options: string[], query: string): string[] {
  const needle = query.trim().toLowerCase();
  if (!needle) {
    return options;
  }
  return options.filter((option) => option.toLowerCase().includes(needle));
}

/**
 * `fetchedModels`, when given, takes priority over the static catalog - used
 * for Ollama once a live "Fetch models" call has returned the server's
 * actual installed models, which is always more accurate than a guess.
 */
export function filterModelSuggestions(
  provider: AIProviderKind | null,
  query: string,
  fetchedModels?: string[] | null,
): string[] {
  if (fetchedModels) {
    return filterList(fetchedModels, query);
  }
  if (!provider) {
    return [];
  }
  // eslint-disable-next-line security/detect-object-injection -- provider is AIProviderKind, not user input
  return filterList(MODEL_SUGGESTIONS[provider], query);
}
