<script setup lang="ts">
import Button from "primevue/button";
import InputNumber from "primevue/inputnumber";
import Message from "primevue/message";
import Select from "primevue/select";
import Skeleton from "primevue/skeleton";
import ToggleSwitch from "primevue/toggleswitch";
import { useToast } from "primevue/usetoast";
import { computed, onMounted, ref } from "vue";

import { ApiError, getLiveViewSettings, listCameras, updateLiveViewSettings } from "@/api";

import type { CameraRead } from "@/api";

const toast = useToast();

const loading = ref(true);
const loadError = ref("");
const saving = ref(false);
const saveError = ref("");

const cameras = ref<CameraRead[]>([]);
const defaultCameraId = ref<string | null>(null);
const autoRefreshEnabled = ref(false);
const autoRefreshIntervalSeconds = ref(10);

const cameraOptions = computed(() => [
  { label: "No default (first camera)", value: null },
  ...cameras.value.map((camera) => ({ label: camera.name, value: camera.id })),
]);

async function load(): Promise<void> {
  loading.value = true;
  loadError.value = "";
  try {
    const [cameraList, settings] = await Promise.all([listCameras(), getLiveViewSettings()]);
    cameras.value = cameraList;
    defaultCameraId.value = settings.default_camera_id;
    autoRefreshEnabled.value = settings.auto_refresh_enabled;
    autoRefreshIntervalSeconds.value = settings.auto_refresh_interval_seconds;
  } catch (caught) {
    loadError.value =
      caught instanceof ApiError ? caught.message : "Could not load Live View settings.";
  } finally {
    loading.value = false;
  }
}

onMounted(load);

async function save(): Promise<void> {
  saveError.value = "";
  saving.value = true;
  try {
    await updateLiveViewSettings({
      default_camera_id: defaultCameraId.value,
      auto_refresh_enabled: autoRefreshEnabled.value,
      auto_refresh_interval_seconds: autoRefreshIntervalSeconds.value,
    });
    toast.add({ severity: "success", summary: "Live View settings saved", life: 2500 });
  } catch (caught) {
    saveError.value = caught instanceof ApiError ? caught.message : "Unexpected error.";
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <article class="panel">
    <h3 class="panel-title">
      Live View
    </h3>
    <p class="panel-hint">
      Defaults for the Live View tab. Auto-refresh here re-fetches whatever a camera last
      captured — it doesn't force a fresh snapshot on every tick.
    </p>

    <div
      v-if="loading"
      data-testid="live-view-settings-loading"
    >
      <Skeleton
        height="140px"
        border-radius="12px"
      />
    </div>

    <Message
      v-else-if="loadError"
      severity="error"
      :closable="false"
      data-testid="live-view-settings-load-error"
    >
      {{ loadError }}
    </Message>

    <form
      v-else
      class="panel-body"
      data-testid="live-view-settings-form"
      @submit.prevent="save"
    >
      <label
        class="field"
        for="default-camera"
      >
        <span class="field-label">Default camera</span>
        <Select
          v-model="defaultCameraId"
          input-id="default-camera"
          :options="cameraOptions"
          option-label="label"
          option-value="value"
          fluid
          data-testid="default-camera"
        />
      </label>

      <div class="toggle-row">
        <ToggleSwitch
          v-model="autoRefreshEnabled"
          data-testid="auto-refresh-default"
        />
        <div>
          <p class="toggle-label">
            Auto-refresh by default
          </p>
          <p class="muted">
            You can still turn this on or off per-visit from Live View itself.
          </p>
        </div>
      </div>

      <label
        class="field"
        for="auto-refresh-interval"
      >
        <span class="field-label">Refresh interval (seconds)</span>
        <InputNumber
          v-model="autoRefreshIntervalSeconds"
          input-id="auto-refresh-interval"
          :min="3"
          :max="120"
          show-buttons
          fluid
          data-testid="auto-refresh-interval"
        />
      </label>

      <Message
        v-if="saveError"
        severity="error"
        :closable="false"
        data-testid="live-view-settings-save-error"
      >
        {{ saveError }}
      </Message>
      <div class="panel-actions">
        <Button
          type="submit"
          label="Save Live View settings"
          :loading="saving"
          data-testid="save-live-view-settings"
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
  gap: 18px;
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

.panel-actions {
  display: flex;
  justify-content: flex-end;
}
</style>
