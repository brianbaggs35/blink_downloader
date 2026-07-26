<script setup lang="ts">
import Button from "primevue/button";
import InputNumber from "primevue/inputnumber";
import Message from "primevue/message";
import Select from "primevue/select";
import Skeleton from "primevue/skeleton";
import Checkbox from "primevue/checkbox";
import { useToast } from "primevue/usetoast";
import { computed, onMounted, ref } from "vue";

import {
  ApiError,
  getSecurityFeedSettings,
  listCameras,
  updateSecurityFeedSettings,
} from "@/api";

import type { CameraRead } from "@/api";

const COLUMN_OPTIONS = [
  { label: "1 column", value: 1 },
  { label: "2 columns", value: 2 },
  { label: "3 columns", value: 3 },
  { label: "4 columns", value: 4 },
];

const toast = useToast();

const loading = ref(true);
const loadError = ref("");
const saving = ref(false);
const saveError = ref("");

const cameras = ref<CameraRead[]>([]);
// Ordered ids of cameras chosen for the feed - empty means "show every
// enabled camera", so this stays useful with zero configuration.
const selectedIds = ref<string[]>([]);
const columns = ref(2);
const refreshIntervalSeconds = ref(20);

const selectedCameras = computed(() =>
  selectedIds.value
    .map((id) => cameras.value.find((camera) => camera.id === id))
    .filter((camera): camera is CameraRead => !!camera),
);
const unselectedCameras = computed(() =>
  cameras.value.filter((camera) => !selectedIds.value.includes(camera.id)),
);

function isChecked(cameraId: string): boolean {
  return selectedIds.value.includes(cameraId);
}

function toggleCamera(cameraId: string, checked: boolean): void {
  if (checked) {
    selectedIds.value = [...selectedIds.value, cameraId];
  } else {
    selectedIds.value = selectedIds.value.filter((id) => id !== cameraId);
  }
}

function moveUp(index: number): void {
  // The button calling this is :disabled at index 0, so a real click can
  // never reach here - kept as a guard against the array corruption a
  // negative-index swap below would otherwise cause if that ever changes.
  /* v8 ignore next */
  if (index === 0) return;
  const next = [...selectedIds.value];
  // index comes from this component's own v-for, bounded by the guard above.
  // eslint-disable-next-line security/detect-object-injection
  [next[index - 1], next[index]] = [next[index]!, next[index - 1]!];
  selectedIds.value = next;
}

function moveDown(index: number): void {
  // Same reasoning as moveUp: the button is :disabled at the last index.
  /* v8 ignore next */
  if (index === selectedIds.value.length - 1) return;
  const next = [...selectedIds.value];
  // eslint-disable-next-line security/detect-object-injection
  [next[index], next[index + 1]] = [next[index + 1]!, next[index]!];
  selectedIds.value = next;
}

async function load(): Promise<void> {
  loading.value = true;
  loadError.value = "";
  try {
    const [cameraList, settings] = await Promise.all([
      listCameras(),
      getSecurityFeedSettings(),
    ]);
    cameras.value = cameraList;
    selectedIds.value = [...settings.camera_ids];
    columns.value = settings.columns;
    refreshIntervalSeconds.value = settings.refresh_interval_seconds;
  } catch (caught) {
    loadError.value =
      caught instanceof ApiError ? caught.message : "Could not load Security Feed settings.";
  } finally {
    loading.value = false;
  }
}

onMounted(load);

async function save(): Promise<void> {
  saveError.value = "";
  saving.value = true;
  try {
    await updateSecurityFeedSettings({
      camera_ids: selectedIds.value,
      columns: columns.value,
      refresh_interval_seconds: refreshIntervalSeconds.value,
    });
    toast.add({ severity: "success", summary: "Security Feed settings saved", life: 2500 });
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
      Security Feed
    </h3>
    <p class="panel-hint">
      Choose which cameras appear on the Security Feed dashboard, their order, and how the grid
      is laid out. Leave every camera unchecked to show all enabled cameras automatically.
    </p>

    <div
      v-if="loading"
      data-testid="security-feed-settings-loading"
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
      data-testid="security-feed-settings-load-error"
    >
      {{ loadError }}
    </Message>

    <Message
      v-else-if="cameras.length === 0"
      severity="info"
      :closable="false"
      data-testid="security-feed-settings-empty"
    >
      No cameras yet — link your Blink account to sync some first.
    </Message>

    <form
      v-else
      class="panel-body"
      data-testid="security-feed-settings-form"
      @submit.prevent="save"
    >
      <div class="tier">
        <h4 class="tier-title">
          Shown, in order
        </h4>
        <p
          v-if="selectedCameras.length === 0"
          class="muted"
        >
          Nothing chosen yet — every enabled camera will show.
        </p>
        <ul
          v-else
          class="camera-order-list"
        >
          <li
            v-for="(camera, index) in selectedCameras"
            :key="camera.id"
            class="camera-row"
          >
            <Checkbox
              :model-value="true"
              binary
              :data-testid="`security-feed-camera-${camera.id}`"
              @update:model-value="(v: boolean) => toggleCamera(camera.id, v)"
            />
            <span class="camera-name">{{ camera.name }}</span>
            <div class="order-buttons">
              <button
                type="button"
                class="order-button"
                :disabled="index === 0"
                :data-testid="`move-up-${camera.id}`"
                @click="moveUp(index)"
              >
                <i class="pi pi-arrow-up" />
              </button>
              <button
                type="button"
                class="order-button"
                :disabled="index === selectedCameras.length - 1"
                :data-testid="`move-down-${camera.id}`"
                @click="moveDown(index)"
              >
                <i class="pi pi-arrow-down" />
              </button>
            </div>
          </li>
        </ul>
      </div>

      <div
        v-if="unselectedCameras.length > 0"
        class="tier"
      >
        <h4 class="tier-title">
          Not shown
        </h4>
        <ul class="camera-order-list">
          <li
            v-for="camera in unselectedCameras"
            :key="camera.id"
            class="camera-row"
          >
            <Checkbox
              :model-value="isChecked(camera.id)"
              binary
              :data-testid="`security-feed-camera-${camera.id}`"
              @update:model-value="(v: boolean) => toggleCamera(camera.id, v)"
            />
            <span class="camera-name">{{ camera.name }}</span>
          </li>
        </ul>
      </div>

      <div class="tier-grid">
        <label class="field">
          <span class="field-label">Grid columns</span>
          <Select
            v-model="columns"
            :options="COLUMN_OPTIONS"
            option-label="label"
            option-value="value"
            fluid
            data-testid="security-feed-columns"
          />
        </label>
        <label class="field">
          <span class="field-label">Refresh interval (seconds)</span>
          <InputNumber
            v-model="refreshIntervalSeconds"
            :min="5"
            :max="300"
            show-buttons
            fluid
            data-testid="security-feed-interval"
          />
        </label>
      </div>

      <Message
        v-if="saveError"
        severity="error"
        :closable="false"
        data-testid="security-feed-settings-save-error"
      >
        {{ saveError }}
      </Message>
      <div class="panel-actions">
        <Button
          type="submit"
          label="Save Security Feed settings"
          :loading="saving"
          data-testid="save-security-feed-settings"
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

.tier {
  padding-top: 16px;
  border-top: 1px solid var(--p-surface-200);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.tier:first-child {
  padding-top: 0;
  border-top: none;
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
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 14px;
}

.camera-order-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.camera-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--p-surface-50);
}

.blink-dark .camera-row {
  background: color-mix(in srgb, var(--p-surface-800) 55%, transparent);
}

.camera-name {
  flex: 1;
  font-size: 0.88rem;
  font-weight: 500;
}

.order-buttons {
  display: flex;
  gap: 4px;
}

.order-button {
  border: none;
  background: none;
  width: 26px;
  height: 26px;
  border-radius: 6px;
  color: var(--p-surface-500);
  cursor: pointer;
}

.order-button:hover:not(:disabled) {
  background: var(--p-surface-200);
  color: var(--p-surface-900);
}

.blink-dark .order-button:hover:not(:disabled) {
  background: var(--p-surface-700);
  color: var(--p-surface-0);
}

.order-button:disabled {
  opacity: 0.35;
  cursor: default;
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

.muted {
  margin: 0;
  font-size: 0.82rem;
  color: var(--p-surface-500);
}

.panel-actions {
  display: flex;
  justify-content: flex-end;
}
</style>
