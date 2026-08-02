<script setup lang="ts">
import AutoComplete, { type AutoCompleteCompleteEvent } from "primevue/autocomplete";
import Button from "primevue/button";
import Checkbox from "primevue/checkbox";
import InputNumber from "primevue/inputnumber";
import InputText from "primevue/inputtext";
import Message from "primevue/message";
import Password from "primevue/password";
import Select from "primevue/select";
import Skeleton from "primevue/skeleton";
import ToggleSwitch from "primevue/toggleswitch";
import { useToast } from "primevue/usetoast";
import { computed, onMounted, reactive, ref, watch } from "vue";
import type { Ref } from "vue";

import {
  ApiError,
  getAiSettings,
  listAiModels,
  testAiAnalysis,
  testAiConnection,
  updateAiSettings,
} from "@/api";
import { filterModelSuggestions, isCloudProvider, isOllamaProvider } from "@/lib/aiProviderCatalog";

import type { AIProviderKind } from "@/api";

const PROVIDER_OPTIONS: { label: string; value: AIProviderKind }[] = [
  { label: "OpenAI", value: "openai" },
  { label: "Anthropic", value: "anthropic" },
  { label: "Ollama (local)", value: "ollama" },
  { label: "Ollama Cloud", value: "ollama_cloud" },
  { label: "Moondream (local)", value: "moondream" },
  { label: "Moondream Cloud", value: "moondream_cloud" },
];

const MODEL_PLACEHOLDER: Record<AIProviderKind, string> = {
  openai: "gpt-4o-mini",
  anthropic: "claude-haiku-4-5",
  ollama: "llava",
  ollama_cloud: "llava",
  moondream: "moondream2",
  moondream_cloud: "moondream2",
};

const BASE_URL_PLACEHOLDER: Record<AIProviderKind, string> = {
  openai: "Default (api.openai.com)",
  anthropic: "Default (api.anthropic.com)",
  ollama: "http://localhost:11434",
  ollama_cloud: "https://ollama.com",
  moondream: "http://localhost:2020/v1",
  moondream_cloud: "https://api.moondream.ai/v1",
};

interface TierForm {
  provider: AIProviderKind | null;
  model: string;
  apiKeyInput: string;
  clearApiKey: boolean;
  apiKeySet: boolean;
  baseUrl: string;
}

function emptyTier(): TierForm {
  return {
    provider: null,
    model: "",
    apiKeyInput: "",
    clearApiKey: false,
    apiKeySet: false,
    baseUrl: "",
  };
}

const toast = useToast();

const loading = ref(true);
const loadError = ref("");
const saving = ref(false);
const saveError = ref("");

const enabled = ref(false);
const tier1 = reactive<TierForm>(emptyTier());
const tier2Enabled = ref(true);
const tier2 = reactive<TierForm>(emptyTier());
const tier2LinkedToTier1 = ref(false);
const keyframesPerClip = ref(4);
const tier2SuspicionThreshold = ref(0.5);
const feedbackContextCount = ref(5);

const tier1ModelSuggestions = ref<string[]>([]);
const tier2ModelSuggestions = ref<string[]>([]);
// Set once "Fetch models" succeeds for Ollama - takes priority over the
// static catalog (see filterModelSuggestions). Reset whenever the provider
// changes, so a stale list from a different server is never shown.
const tier1FetchedModels = ref<string[] | null>(null);
const tier2FetchedModels = ref<string[] | null>(null);
const tier1FetchingModels = ref(false);
const tier2FetchingModels = ref(false);
const tier1FetchModelsError = ref("");
const tier2FetchModelsError = ref("");

function onModelComplete(tier: "tier1" | "tier2", event: AutoCompleteCompleteEvent): void {
  const provider = tier === "tier1" ? tier1.provider : effectiveTier2Provider.value;
  const suggestions = tier === "tier1" ? tier1ModelSuggestions : tier2ModelSuggestions;
  const fetched = tier === "tier1" ? tier1FetchedModels.value : tier2FetchedModels.value;
  suggestions.value = filterModelSuggestions(provider, event.query, fetched);
}

async function fetchModels(tierName: "tier1" | "tier2"): Promise<void> {
  const fetchedModels = tierName === "tier1" ? tier1FetchedModels : tier2FetchedModels;
  const fetching = tierName === "tier1" ? tier1FetchingModels : tier2FetchingModels;
  const fetchError = tierName === "tier1" ? tier1FetchModelsError : tier2FetchModelsError;
  const source = testCredentialSource(tierName);
  fetching.value = true;
  fetchError.value = "";
  try {
    const response = await listAiModels({
      tier: source.tier,
      // The Fetch-models button only renders when isOllamaProvider(...) is
      // already true, so source.provider is never null here.
      provider: source.provider!,
      api_key: source.apiKeyInput || null,
      base_url: source.baseUrl || null,
    });
    if (response.ok) {
      fetchedModels.value = response.models ?? [];
    } else {
      fetchError.value = response.detail ?? "Could not fetch models.";
    }
  } catch (caught) {
    fetchError.value = caught instanceof ApiError ? caught.message : "Could not fetch models.";
  } finally {
    fetching.value = false;
  }
}

// Tier 2's provider fields are hidden while linked, so anything needing
// "whichever provider tier 2 will actually use" reads through this instead.
const effectiveTier2Provider = computed<AIProviderKind | null>(() =>
  tier2LinkedToTier1.value ? tier1.provider : tier2.provider,
);

function providerLabel(kind: AIProviderKind | null): string {
  // Only ever called with tier1.provider from behind a v-if="...&& tier1.provider"
  // guard, so the fallback is unreachable through real UI interaction.
  /* v8 ignore next */
  return PROVIDER_OPTIONS.find((option) => option.value === kind)?.label ?? "";
}

async function load(): Promise<void> {
  loading.value = true;
  loadError.value = "";
  try {
    const settings = await getAiSettings();
    enabled.value = settings.enabled;
    tier1.provider = settings.tier1_provider;
    tier1.model = settings.tier1_model ?? "";
    tier1.apiKeySet = settings.tier1_api_key_set;
    tier1.baseUrl = settings.tier1_base_url ?? "";
    tier2Enabled.value = settings.tier2_enabled;
    tier2.provider = settings.tier2_provider;
    tier2.model = settings.tier2_model ?? "";
    tier2.apiKeySet = settings.tier2_api_key_set;
    tier2.baseUrl = settings.tier2_base_url ?? "";
    tier2LinkedToTier1.value = settings.tier2_linked_to_tier1;
    keyframesPerClip.value = settings.keyframes_per_clip;
    tier2SuspicionThreshold.value = settings.tier2_suspicion_threshold;
    feedbackContextCount.value = settings.feedback_context_count;
  } catch (caught) {
    loadError.value = caught instanceof ApiError ? caught.message : "Could not load AI settings.";
  } finally {
    loading.value = false;
  }
}

onMounted(load);

// Drop a now-hidden/stale base URL on a cloud provider. resolvedBaseUrl()
// already keeps a cloud provider's saved value null regardless, so this is
// purely so the (otherwise-hidden) field doesn't hold a stale value if the
// user switches back to a self-hosted provider later in the same session.
watch(
  () => tier1.provider,
  () => {
    tier1FetchedModels.value = null;
    if (isCloudProvider(tier1.provider)) {
      tier1.baseUrl = "";
    }
    if (!tier1.provider) {
      tier2LinkedToTier1.value = false;
    }
  },
);
watch(
  () => tier2.provider,
  () => {
    tier2FetchedModels.value = null;
    if (isCloudProvider(tier2.provider)) {
      tier2.baseUrl = "";
    }
  },
);

function resolvedApiKey(tier: TierForm): string | null {
  if (tier.apiKeyInput) {
    return tier.apiKeyInput;
  }
  return tier.clearApiKey ? "" : null;
}

function resolvedBaseUrl(provider: AIProviderKind | null, baseUrl: string): string | null {
  return isCloudProvider(provider) ? null : baseUrl || null;
}

async function save(): Promise<void> {
  saveError.value = "";
  saving.value = true;
  try {
    const settings = await updateAiSettings({
      enabled: enabled.value,
      tier1_provider: tier1.provider,
      tier1_model: tier1.model || null,
      tier1_api_key: resolvedApiKey(tier1),
      tier1_base_url: resolvedBaseUrl(tier1.provider, tier1.baseUrl),
      tier2_enabled: tier2Enabled.value,
      tier2_provider: tier2.provider,
      tier2_model: tier2.model || null,
      tier2_api_key: resolvedApiKey(tier2),
      tier2_base_url: resolvedBaseUrl(tier2.provider, tier2.baseUrl),
      tier2_linked_to_tier1: tier2LinkedToTier1.value,
      keyframes_per_clip: keyframesPerClip.value,
      tier2_suspicion_threshold: tier2SuspicionThreshold.value,
      feedback_context_count: feedbackContextCount.value,
    });
    tier1.apiKeySet = settings.tier1_api_key_set;
    tier1.apiKeyInput = "";
    tier1.clearApiKey = false;
    tier2.apiKeySet = settings.tier2_api_key_set;
    tier2.apiKeyInput = "";
    tier2.clearApiKey = false;
    toast.add({ severity: "success", summary: "AI settings saved", life: 2500 });
  } catch (caught) {
    saveError.value = caught instanceof ApiError ? caught.message : "Unexpected error.";
  } finally {
    saving.value = false;
  }
}

const testingTier1 = ref(false);
const testingTier2 = ref(false);
const tier1TestResult = ref<{ ok: boolean; detail: string } | null>(null);
const tier2TestResult = ref<{ ok: boolean; detail: string } | null>(null);

const testingTier1Analysis = ref(false);
const testingTier2Analysis = ref(false);
const tier1AnalysisResult = ref<{ ok: boolean; detail: string } | null>(null);
const tier2AnalysisResult = ref<{ ok: boolean; detail: string } | null>(null);

interface TestCredentialSource {
  tier: "tier1" | "tier2";
  provider: AIProviderKind | null;
  apiKeyInput: string;
  baseUrl: string;
}

// Tier 2's own fields are inert while linked - route the test call through
// tier1's live form values, with tier:"tier1" so an omitted key falls back
// to tier1's saved one, not tier2's stale one.
function testCredentialSource(tierName: "tier1" | "tier2"): TestCredentialSource {
  if (tierName === "tier2" && tier2LinkedToTier1.value) {
    return {
      tier: "tier1",
      provider: tier1.provider,
      apiKeyInput: tier1.apiKeyInput,
      baseUrl: tier1.baseUrl,
    };
  }
  const form = tierName === "tier1" ? tier1 : tier2;
  return {
    tier: tierName,
    provider: form.provider,
    apiKeyInput: form.apiKeyInput,
    baseUrl: form.baseUrl,
  };
}

interface TierTestRefs {
  testing: Ref<boolean>;
  result: Ref<{ ok: boolean; detail: string } | null>;
}

function tierTestRefs(tierName: "tier1" | "tier2", kind: "connection" | "analysis"): TierTestRefs {
  if (tierName === "tier1") {
    return kind === "connection"
      ? { testing: testingTier1, result: tier1TestResult }
      : { testing: testingTier1Analysis, result: tier1AnalysisResult };
  }
  return kind === "connection"
    ? { testing: testingTier2, result: tier2TestResult }
    : { testing: testingTier2Analysis, result: tier2AnalysisResult };
}

async function runTierTest(
  tierName: "tier1" | "tier2",
  kind: "connection" | "analysis",
): Promise<void> {
  const form = tierName === "tier1" ? tier1 : tier2;
  const source = testCredentialSource(tierName);
  const { testing, result } = tierTestRefs(tierName, kind);
  if (!source.provider || !form.model) {
    result.value = { ok: false, detail: "Choose a provider and model first." };
    return;
  }
  testing.value = true;
  result.value = null;
  try {
    const call = kind === "connection" ? testAiConnection : testAiAnalysis;
    const response = await call({
      tier: source.tier,
      provider: source.provider,
      model: form.model,
      api_key: source.apiKeyInput || null,
      base_url: source.baseUrl || null,
    });
    const fallback = response.ok ? "Connected." : "Failed.";
    result.value = { ok: response.ok, detail: response.detail ?? fallback };
  } catch (caught) {
    result.value = {
      ok: false,
      detail: caught instanceof ApiError ? caught.message : "Unexpected error.",
    };
  } finally {
    testing.value = false;
  }
}

const tier1KeyPlaceholder = computed(() =>
  tier1.apiKeySet ? "•••••••••••• (saved — leave blank to keep)" : "Not set",
);
const tier2KeyPlaceholder = computed(() =>
  tier2.apiKeySet ? "•••••••••••• (saved — leave blank to keep)" : "Not set",
);
</script>

<template>
  <article class="panel">
    <h3 class="panel-title">
      AI Provider
    </h3>
    <p class="panel-hint">
      Configure the vision models that analyze your clips. Tier 1 screens every clip cheaply;
      Tier 2 re-examines anything Tier 1 flags as suspicious with a stronger model.
    </p>

    <div
      v-if="loading"
      data-testid="ai-provider-loading"
    >
      <Skeleton
        height="220px"
        border-radius="12px"
      />
    </div>

    <Message
      v-else-if="loadError"
      severity="error"
      :closable="false"
      data-testid="ai-provider-load-error"
    >
      {{ loadError }}
    </Message>

    <form
      v-else
      class="panel-body"
      data-testid="ai-provider-form"
      @submit.prevent="save"
    >
      <div class="toggle-row">
        <ToggleSwitch
          v-model="enabled"
          data-testid="ai-enabled"
        />
        <div>
          <p class="toggle-label">
            Enable AI analysis
          </p>
          <p class="muted">
            When off, downloaded clips are stored but never analyzed.
          </p>
        </div>
      </div>

      <section class="tier">
        <h4 class="tier-title">
          Tier 1 — first pass
        </h4>
        <div class="tier-grid">
          <label
            class="field"
            for="tier1-provider"
          >
            <span class="field-label">Provider</span>
            <Select
              v-model="tier1.provider"
              :options="PROVIDER_OPTIONS"
              option-label="label"
              option-value="value"
              placeholder="Choose a provider"
              fluid
              label-id="tier1-provider"
              data-testid="tier1-provider"
            />
          </label>
          <label
            class="field"
            for="tier1-model"
          >
            <span class="field-label">Model</span>
            <AutoComplete
              v-model="tier1.model"
              :suggestions="tier1ModelSuggestions"
              dropdown
              fluid
              input-id="tier1-model"
              :placeholder="tier1.provider ? MODEL_PLACEHOLDER[tier1.provider] : ''"
              :pt="{ pcInputText: { root: { 'data-testid': 'tier1-model' } } }"
              @complete="onModelComplete('tier1', $event)"
            />
            <div
              v-if="isOllamaProvider(tier1.provider)"
              class="fetch-models-row"
            >
              <Button
                type="button"
                label="Fetch models"
                severity="secondary"
                text
                size="small"
                :loading="tier1FetchingModels"
                data-testid="tier1-fetch-models"
                @click="fetchModels('tier1')"
              />
              <span
                v-if="tier1FetchModelsError"
                class="fetch-models-error"
                data-testid="tier1-fetch-models-error"
              >
                {{ tier1FetchModelsError }}
              </span>
            </div>
          </label>
          <label
            class="field"
            for="tier1-api-key"
          >
            <span class="field-label">API key</span>
            <Password
              v-model="tier1.apiKeyInput"
              :feedback="false"
              toggle-mask
              fluid
              input-id="tier1-api-key"
              :placeholder="tier1KeyPlaceholder"
              data-testid="tier1-api-key"
            />
          </label>
          <label
            v-if="!isCloudProvider(tier1.provider)"
            class="field"
            for="tier1-base-url"
          >
            <span class="field-label">Base URL (optional)</span>
            <InputText
              id="tier1-base-url"
              v-model="tier1.baseUrl"
              :placeholder="tier1.provider ? BASE_URL_PLACEHOLDER[tier1.provider] : ''"
              fluid
              data-testid="tier1-base-url"
            />
          </label>
        </div>
        <label
          v-if="tier1.apiKeySet"
          class="clear-key"
          for="tier1-clear-key"
        >
          <Checkbox
            v-model="tier1.clearApiKey"
            binary
            input-id="tier1-clear-key"
            data-testid="tier1-clear-key"
          />
          Remove the saved key on next save
        </label>
        <div class="test-row">
          <Button
            type="button"
            label="Test connection"
            severity="secondary"
            outlined
            size="small"
            :loading="testingTier1"
            data-testid="tier1-test"
            @click="runTierTest('tier1', 'connection')"
          />
          <Button
            type="button"
            label="Run test analysis"
            severity="secondary"
            outlined
            size="small"
            :loading="testingTier1Analysis"
            data-testid="tier1-test-analysis"
            @click="runTierTest('tier1', 'analysis')"
          />
        </div>
        <span
          v-if="tier1TestResult"
          :class="['test-result', tier1TestResult.ok ? 'ok' : 'fail']"
          data-testid="tier1-test-result"
        >
          <i :class="tier1TestResult.ok ? 'pi pi-check-circle' : 'pi pi-times-circle'" />
          {{ tier1TestResult.detail }}
        </span>
        <span
          v-if="tier1AnalysisResult"
          :class="['test-result', tier1AnalysisResult.ok ? 'ok' : 'fail']"
          data-testid="tier1-test-analysis-result"
        >
          <i :class="tier1AnalysisResult.ok ? 'pi pi-check-circle' : 'pi pi-times-circle'" />
          {{ tier1AnalysisResult.detail }}
        </span>
      </section>

      <section class="tier">
        <div class="toggle-row">
          <ToggleSwitch
            v-model="tier2Enabled"
            data-testid="tier2-enabled"
          />
          <div>
            <p class="toggle-label">
              Tier 2 — escalation
            </p>
            <p class="muted">
              Re-analyzes clips Tier 1 scores above the threshold below, with a stronger model.
            </p>
          </div>
        </div>

        <template v-if="tier2Enabled">
          <label
            class="toggle-row link-tier1-row"
            for="tier2-link-to-tier1"
          >
            <ToggleSwitch
              v-model="tier2LinkedToTier1"
              :disabled="!tier1.provider"
              input-id="tier2-link-to-tier1"
              data-testid="tier2-link-to-tier1"
            />
            <div>
              <p class="toggle-label">
                Use Tier 1's provider &amp; API key
              </p>
              <p class="muted">
                Keep the same provider and API key as Tier 1 — you can still choose a different
                model below.
              </p>
            </div>
          </label>
          <p
            v-if="tier2LinkedToTier1 && tier1.provider"
            class="linked-note"
            data-testid="tier2-linked-note"
          >
            Using Tier 1's provider ({{ providerLabel(tier1.provider) }}) and API key.
          </p>

          <div class="tier-grid">
            <label
              v-if="!tier2LinkedToTier1"
              class="field"
              for="tier2-provider"
            >
              <span class="field-label">Provider</span>
              <Select
                v-model="tier2.provider"
                :options="PROVIDER_OPTIONS"
                option-label="label"
                option-value="value"
                placeholder="Choose a provider"
                fluid
                label-id="tier2-provider"
                data-testid="tier2-provider"
              />
            </label>
            <label
              class="field"
              for="tier2-model"
            >
              <span class="field-label">Model</span>
              <AutoComplete
                v-model="tier2.model"
                :suggestions="tier2ModelSuggestions"
                dropdown
                fluid
                input-id="tier2-model"
                :placeholder="effectiveTier2Provider ? MODEL_PLACEHOLDER[effectiveTier2Provider] : ''"
                :pt="{ pcInputText: { root: { 'data-testid': 'tier2-model' } } }"
                @complete="onModelComplete('tier2', $event)"
              />
              <div
                v-if="isOllamaProvider(effectiveTier2Provider)"
                class="fetch-models-row"
              >
                <Button
                  type="button"
                  label="Fetch models"
                  severity="secondary"
                  text
                  size="small"
                  :loading="tier2FetchingModels"
                  data-testid="tier2-fetch-models"
                  @click="fetchModels('tier2')"
                />
                <span
                  v-if="tier2FetchModelsError"
                  class="fetch-models-error"
                  data-testid="tier2-fetch-models-error"
                >
                  {{ tier2FetchModelsError }}
                </span>
              </div>
            </label>
            <label
              v-if="!tier2LinkedToTier1"
              class="field"
              for="tier2-api-key"
            >
              <span class="field-label">API key</span>
              <Password
                v-model="tier2.apiKeyInput"
                :feedback="false"
                toggle-mask
                fluid
                input-id="tier2-api-key"
                :placeholder="tier2KeyPlaceholder"
                data-testid="tier2-api-key"
              />
            </label>
            <label
              v-if="!tier2LinkedToTier1 && !isCloudProvider(tier2.provider)"
              class="field"
              for="tier2-base-url"
            >
              <span class="field-label">Base URL (optional)</span>
              <InputText
                id="tier2-base-url"
                v-model="tier2.baseUrl"
                :placeholder="tier2.provider ? BASE_URL_PLACEHOLDER[tier2.provider] : ''"
                fluid
                data-testid="tier2-base-url"
              />
            </label>
          </div>
          <label
            v-if="!tier2LinkedToTier1 && tier2.apiKeySet"
            class="clear-key"
            for="tier2-clear-key"
          >
            <Checkbox
              v-model="tier2.clearApiKey"
              binary
              input-id="tier2-clear-key"
              data-testid="tier2-clear-key"
            />
            Remove the saved key on next save
          </label>
          <div class="test-row">
            <Button
              type="button"
              label="Test connection"
              severity="secondary"
              outlined
              size="small"
              :loading="testingTier2"
              data-testid="tier2-test"
              @click="runTierTest('tier2', 'connection')"
            />
            <Button
              type="button"
              label="Run test analysis"
              severity="secondary"
              outlined
              size="small"
              :loading="testingTier2Analysis"
              data-testid="tier2-test-analysis"
              @click="runTierTest('tier2', 'analysis')"
            />
          </div>
          <span
            v-if="tier2TestResult"
            :class="['test-result', tier2TestResult.ok ? 'ok' : 'fail']"
            data-testid="tier2-test-result"
          >
            <i :class="tier2TestResult.ok ? 'pi pi-check-circle' : 'pi pi-times-circle'" />
            {{ tier2TestResult.detail }}
          </span>
          <span
            v-if="tier2AnalysisResult"
            :class="['test-result', tier2AnalysisResult.ok ? 'ok' : 'fail']"
            data-testid="tier2-test-analysis-result"
          >
            <i :class="tier2AnalysisResult.ok ? 'pi pi-check-circle' : 'pi pi-times-circle'" />
            {{ tier2AnalysisResult.detail }}
          </span>
        </template>
      </section>

      <section class="tier">
        <h4 class="tier-title">
          Tuning
        </h4>
        <div class="tier-grid">
          <label
            class="field"
            for="keyframes-per-clip"
          >
            <span class="field-label">Keyframes per clip</span>
            <InputNumber
              v-model="keyframesPerClip"
              :min="1"
              :max="12"
              show-buttons
              fluid
              input-id="keyframes-per-clip"
              data-testid="keyframes-per-clip"
            />
          </label>
          <label
            class="field"
            for="suspicion-threshold"
          >
            <span class="field-label">Tier 2 suspicion threshold</span>
            <InputNumber
              v-model="tier2SuspicionThreshold"
              :min="0"
              :max="1"
              :step="0.05"
              :min-fraction-digits="2"
              show-buttons
              fluid
              input-id="suspicion-threshold"
              data-testid="suspicion-threshold"
            />
          </label>
          <label
            class="field"
            for="feedback-context-count"
          >
            <span class="field-label">Feedback examples per prompt</span>
            <InputNumber
              v-model="feedbackContextCount"
              :min="0"
              :max="20"
              show-buttons
              fluid
              input-id="feedback-context-count"
              data-testid="feedback-context-count"
            />
          </label>
        </div>
      </section>

      <Message
        v-if="saveError"
        severity="error"
        :closable="false"
        data-testid="ai-provider-save-error"
      >
        {{ saveError }}
      </Message>
      <div class="panel-actions">
        <Button
          type="submit"
          label="Save AI settings"
          :loading="saving"
          data-testid="save-ai-settings"
        />
      </div>
    </form>
  </article>
</template>

<style scoped>
.panel {
  padding: 22px 24px;
  border-radius: 14px;
  border: 1px solid var(--p-surface-200);
  background: var(--p-surface-0);
}

.blink-dark .panel {
  border-color: var(--p-surface-800);
  background: color-mix(in srgb, var(--p-surface-900) 60%, transparent);
}

.panel-title {
  margin: 0;
  font-size: 1rem;
  font-weight: 700;
}

.panel-hint {
  margin: 4px 0 16px;
  font-size: 0.82rem;
  color: var(--p-surface-500);
  max-width: 70ch;
}

.panel-body {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.toggle-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.toggle-label {
  margin: 0;
  font-size: 0.9rem;
  font-weight: 600;
}

.muted {
  margin: 2px 0 0;
  font-size: 0.8rem;
  color: var(--p-surface-500);
}

.tier {
  padding-top: 16px;
  border-top: 1px solid var(--p-surface-200);
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.blink-dark .tier {
  border-color: var(--p-surface-800);
}

.tier-title {
  margin: 0;
  font-size: 0.88rem;
  font-weight: 700;
}

.tier-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 14px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field-label {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--p-surface-600);
}

.blink-dark .field-label {
  color: var(--p-surface-300);
}

.clear-key {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.82rem;
  color: var(--p-surface-600);
}

.blink-dark .clear-key {
  color: var(--p-surface-300);
}

.linked-note {
  margin: -6px 0 0;
  font-size: 0.82rem;
  font-style: italic;
  color: var(--p-surface-500);
}

.fetch-models-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.fetch-models-error {
  font-size: 0.78rem;
  color: var(--p-red-500);
}

.test-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.test-result {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 0.82rem;
  font-weight: 600;
}

.test-result.ok {
  color: var(--p-green-600);
}

.test-result.fail {
  color: var(--p-red-500);
}

.panel-actions {
  display: flex;
  justify-content: flex-end;
}
</style>
