<script setup lang="ts">
import Button from "primevue/button";
import InputNumber from "primevue/inputnumber";
import Message from "primevue/message";
import Select from "primevue/select";
import Skeleton from "primevue/skeleton";
import Tag from "primevue/tag";
import ToggleSwitch from "primevue/toggleswitch";
import { useToast } from "primevue/usetoast";
import { onMounted, ref } from "vue";

import { ApiError, getBiometricsSettings, updateBiometricsSettings, verifyBiometricsModel } from "@/api";

import type { ExecutionProviderPreference, ModelPack } from "@/api";

const MODEL_PACK_OPTIONS: { label: string; value: ModelPack; hint: string }[] = [
  {
    label: "Fastest (smallest)",
    value: "buffalo_sc",
    hint: "Lowest accuracy, but runs well on low-power devices like a Raspberry Pi.",
  },
  {
    label: "Fast",
    value: "buffalo_s",
    hint: "A good balance for modest CPUs without a lot of headroom.",
  },
  {
    label: "Balanced",
    value: "buffalo_m",
    hint: "Recommended default for most systems.",
  },
  {
    label: "Most accurate (largest)",
    value: "buffalo_l",
    hint: "Best accuracy, at the cost of more CPU or GPU work per clip.",
  },
];

const PROVIDER_PREFERENCE_OPTIONS: { label: string; value: ExecutionProviderPreference }[] = [
  { label: "Auto — use a GPU if one is available", value: "auto" },
  { label: "CPU only", value: "cpu" },
];

const toast = useToast();

const loading = ref(true);
const loadError = ref("");
const saving = ref(false);
const saveError = ref("");

const enabled = ref(false);
const modelPack = ref<ModelPack>("buffalo_l");
const providerPreference = ref<ExecutionProviderPreference>("auto");
const recognitionThreshold = ref(0.4);
const availableProviders = ref<string[]>([]);

const verifying = ref(false);
const verifyError = ref("");
const verifyResult = ref<{ providers: string[] } | null>(null);

async function load(): Promise<void> {
  loading.value = true;
  loadError.value = "";
  try {
    const settings = await getBiometricsSettings();
    enabled.value = settings.enabled;
    modelPack.value = settings.model_pack;
    providerPreference.value = settings.execution_provider_preference;
    recognitionThreshold.value = settings.recognition_threshold;
    availableProviders.value = settings.available_providers;
  } catch (caught) {
    loadError.value =
      caught instanceof ApiError ? caught.message : "Could not load biometrics settings.";
  } finally {
    loading.value = false;
  }
}

onMounted(load);

async function save(): Promise<void> {
  saveError.value = "";
  saving.value = true;
  try {
    const settings = await updateBiometricsSettings({
      enabled: enabled.value,
      model_pack: modelPack.value,
      execution_provider_preference: providerPreference.value,
      recognition_threshold: recognitionThreshold.value,
    });
    availableProviders.value = settings.available_providers;
    toast.add({ severity: "success", summary: "Biometrics settings saved", life: 2500 });
  } catch (caught) {
    saveError.value = caught instanceof ApiError ? caught.message : "Unexpected error.";
  } finally {
    saving.value = false;
  }
}

const gpuDetected = () => availableProviders.value.some((p) => p !== "CPUExecutionProvider");

async function verifyModel(): Promise<void> {
  verifyError.value = "";
  verifyResult.value = null;
  verifying.value = true;
  try {
    const result = await verifyBiometricsModel();
    verifyResult.value = { providers: result.providers };
    toast.add({ severity: "success", summary: "Model ready", life: 3000 });
  } catch (caught) {
    verifyError.value =
      caught instanceof ApiError
        ? caught.message
        : "Could not verify the model. Check your connection and try again.";
  } finally {
    verifying.value = false;
  }
}
</script>

<template>
  <article class="panel">
    <h3 class="panel-title">
      Facial Recognition
    </h3>
    <p class="panel-hint">
      Detects and matches faces against people you've enrolled in the Biometrics tab, entirely on
      this server — no image, embedding, or name is ever sent to an AI provider. Enrollment works
      whether or not this is enabled; this switch only controls automatic recognition during clip
      analysis.
    </p>

    <div
      v-if="loading"
      data-testid="biometrics-settings-loading"
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
      data-testid="biometrics-settings-load-error"
    >
      {{ loadError }}
    </Message>

    <form
      v-else
      class="panel-body"
      data-testid="biometrics-settings-form"
      @submit.prevent="save"
    >
      <div class="toggle-row">
        <ToggleSwitch
          v-model="enabled"
          data-testid="biometrics-enabled"
        />
        <div>
          <p class="toggle-label">
            Recognize enrolled people automatically
          </p>
          <p class="muted">
            When off, clips are analyzed as before and nobody is auto-recognized.
          </p>
        </div>
      </div>

      <div class="tier-grid">
        <label class="field">
          <span class="field-label">Model</span>
          <Select
            v-model="modelPack"
            :options="MODEL_PACK_OPTIONS"
            option-label="label"
            option-value="value"
            fluid
            data-testid="biometrics-model-pack"
          />
          <span class="muted">
            {{ MODEL_PACK_OPTIONS.find((o) => o.value === modelPack)?.hint }}
          </span>
        </label>
        <label class="field">
          <span class="field-label">Compute</span>
          <Select
            v-model="providerPreference"
            :options="PROVIDER_PREFERENCE_OPTIONS"
            option-label="label"
            option-value="value"
            fluid
            data-testid="biometrics-provider-preference"
          />
          <span class="muted">
            Detected on this server:
            <Tag
              :value="gpuDetected() ? 'GPU available' : 'CPU only'"
              :severity="gpuDetected() ? 'success' : 'secondary'"
              data-testid="biometrics-detected-providers"
            />
          </span>
        </label>
        <label class="field">
          <span class="field-label">Match confidence threshold</span>
          <InputNumber
            v-model="recognitionThreshold"
            :min="0"
            :max="1"
            :step="0.05"
            :min-fraction-digits="2"
            show-buttons
            fluid
            data-testid="biometrics-threshold"
          />
          <span class="muted">
            Higher means fewer false matches, but a harder time recognizing someone from an
            unusual angle.
          </span>
        </label>
      </div>

      <div class="verify-row">
        <Button
          type="button"
          label="Verify / download model"
          icon="pi pi-cloud-download"
          severity="secondary"
          outlined
          :disabled="!enabled"
          :loading="verifying"
          data-testid="verify-model"
          @click="verifyModel"
        />
        <span class="muted">
          Downloads the selected model now (first use otherwise downloads it during your next
          clip analysis, adding a delay). Requires internet access on this one occasion only —
          nothing from your cameras is ever sent anywhere.
        </span>
      </div>
      <Message
        v-if="verifyResult"
        severity="success"
        :closable="false"
        data-testid="verify-model-success"
      >
        Model ready — running on {{ verifyResult.providers.join(", ") }}.
      </Message>
      <Message
        v-if="verifyError"
        severity="error"
        :closable="false"
        data-testid="verify-model-error"
      >
        {{ verifyError }}
      </Message>

      <Message
        v-if="saveError"
        severity="error"
        :closable="false"
        data-testid="biometrics-settings-save-error"
      >
        {{ saveError }}
      </Message>
      <div class="panel-actions">
        <Button
          type="submit"
          label="Save biometrics settings"
          :loading="saving"
          data-testid="save-biometrics-settings"
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

.panel-actions {
  display: flex;
  justify-content: flex-end;
}

.verify-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border-radius: 10px;
  background: var(--p-surface-100);
}

.blink-dark .verify-row {
  background: color-mix(in srgb, var(--p-surface-800) 60%, transparent);
}

.verify-row .muted {
  flex: 1 1 260px;
  margin: 0;
}
</style>
