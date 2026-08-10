<script setup lang="ts">
import Button from "primevue/button";
import Message from "primevue/message";
import Skeleton from "primevue/skeleton";
import Tag from "primevue/tag";
import Textarea from "primevue/textarea";
import ToggleSwitch from "primevue/toggleswitch";
import { useToast } from "primevue/usetoast";
import { computed, onMounted, reactive, ref } from "vue";

import { ApiError, listCameras, updateCamera } from "@/api";
import BatteryIndicator from "@/components/BatteryIndicator.vue";
import { cameraModelLabel } from "@/lib/cameraModels";

import type { CameraRead } from "@/api";

const toast = useToast();

const cameras = ref<CameraRead[]>([]);
const loading = ref(true);
const loadError = ref("");

const contextDrafts = reactive<Record<string, string>>({});
const savingEnabled = reactive<Record<string, boolean>>({});
const savingContext = reactive<Record<string, boolean>>({});
const savingAll = ref(false);

async function load(): Promise<void> {
  loading.value = true;
  loadError.value = "";
  try {
    cameras.value = await listCameras();
    for (const camera of cameras.value) {
      contextDrafts[camera.id] = camera.security_context ?? "";
    }
  } catch (caught) {
    loadError.value = caught instanceof ApiError ? caught.message : "Could not load cameras.";
  } finally {
    loading.value = false;
  }
}

onMounted(load);

async function toggleEnabled(camera: CameraRead, value: boolean): Promise<void> {
  savingEnabled[camera.id] = true;
  try {
    const updated = await updateCamera(camera.id, value, camera.security_context);
    // Cameras are only ever loaded once and updated in place, never removed,
    // so the id we just toggled is always still present.
    const index = cameras.value.findIndex((c) => c.id === camera.id);
    // eslint-disable-next-line security/detect-object-injection
    cameras.value[index] = updated;
  } catch (caught) {
    toast.add({
      severity: "error",
      summary: "Could not update camera",
      detail: caught instanceof ApiError ? caught.message : "Unexpected error.",
      life: 4000,
    });
  } finally {
    savingEnabled[camera.id] = false;
  }
}

async function saveContext(camera: CameraRead): Promise<void> {
  savingContext[camera.id] = true;
  try {
    const updated = await updateCamera(camera.id, camera.enabled, contextDrafts[camera.id] || null);
    const index = cameras.value.findIndex((c) => c.id === camera.id);
    // eslint-disable-next-line security/detect-object-injection
    cameras.value[index] = updated;
    toast.add({ severity: "success", summary: "Camera context saved", life: 2200 });
  } catch (caught) {
    toast.add({
      severity: "error",
      summary: "Could not save context",
      detail: caught instanceof ApiError ? caught.message : "Unexpected error.",
      life: 4000,
    });
  } finally {
    savingContext[camera.id] = false;
  }
}

function contextChanged(camera: CameraRead): boolean {
  // load() always seeds contextDrafts for every camera before any row can
  // render, so the draft side is never actually missing here.
  return contextDrafts[camera.id] !== (camera.security_context ?? "");
}

const anyDirty = computed(() => cameras.value.some(contextChanged));

async function saveAllContexts(): Promise<void> {
  // Only ever wired to the Save-all button, which is :disabled="!anyDirty"
  // - a disabled PrimeVue Button never fires @click, so targets is
  // guaranteed non-empty here.
  const targets = cameras.value.filter(contextChanged);
  savingAll.value = true;
  for (const camera of targets) {
    savingContext[camera.id] = true;
  }
  try {
    const results = await Promise.allSettled(
      targets.map(async (camera) => {
        const updated = await updateCamera(camera.id, camera.enabled, contextDrafts[camera.id] || null);
        const index = cameras.value.findIndex((c) => c.id === camera.id);
        // eslint-disable-next-line security/detect-object-injection
        cameras.value[index] = updated;
      }),
    );
    const failed = results.filter((result) => result.status === "rejected").length;
    const succeeded = results.length - failed;
    toast.add({
      severity: failed > 0 ? "warn" : "success",
      summary: `Saved ${succeeded} camera context${succeeded === 1 ? "" : "s"}`,
      detail: failed > 0 ? `${failed} could not be saved.` : undefined,
      life: 3500,
    });
  } finally {
    for (const camera of targets) {
      savingContext[camera.id] = false;
    }
    savingAll.value = false;
  }
}
</script>

<template>
  <article class="panel">
    <div class="panel-header-row">
      <h3 class="panel-title">
        Cameras
      </h3>
      <Button
        label="Save all"
        size="small"
        :loading="savingAll"
        :disabled="!anyDirty || savingAll"
        data-testid="camera-save-all"
        @click="saveAllContexts"
      />
    </div>
    <p class="panel-hint">
      Turn syncing off for cameras you don't want downloaded or analyzed, and give the AI context
      about what each camera watches — this is included in every analysis prompt for that camera.
    </p>

    <div
      v-if="loading"
      data-testid="cameras-loading"
    >
      <Skeleton
        v-for="n in 3"
        :key="n"
        height="120px"
        border-radius="12px"
        class="camera-skeleton"
      />
    </div>

    <Message
      v-else-if="loadError"
      severity="error"
      :closable="false"
      data-testid="cameras-load-error"
    >
      {{ loadError }}
    </Message>

    <Message
      v-else-if="cameras.length === 0"
      severity="info"
      :closable="false"
      data-testid="cameras-empty"
    >
      No cameras yet. Link your Blink account in the General tab to sync your cameras.
    </Message>

    <div
      v-else
      class="camera-list"
      data-testid="camera-list"
    >
      <article
        v-for="camera in cameras"
        :key="camera.id"
        class="camera-row"
        :data-testid="`camera-row-${camera.id}`"
      >
        <div class="camera-header">
          <div class="camera-identity">
            <span class="camera-name">{{ camera.name }}</span>
            <Tag
              :value="cameraModelLabel(camera.camera_type)"
              severity="secondary"
            />
            <BatteryIndicator
              v-if="camera.battery"
              :battery="camera.battery"
              :data-testid="`camera-battery-${camera.id}`"
            />
          </div>
          <div class="camera-toggle">
            <span class="muted">{{ camera.enabled ? "Syncing" : "Paused" }}</span>
            <ToggleSwitch
              :model-value="camera.enabled"
              :disabled="savingEnabled[camera.id]"
              :data-testid="`camera-enabled-${camera.id}`"
              @update:model-value="(v: boolean) => toggleEnabled(camera, v)"
            />
          </div>
        </div>
        <label
          class="field"
          :for="`camera-context-${camera.id}`"
        >
          <span class="field-label">AI context for this camera</span>
          <Textarea
            :id="`camera-context-${camera.id}`"
            v-model="contextDrafts[camera.id]"
            rows="2"
            auto-resize
            placeholder="e.g. Watches the driveway. A silver sedan is normally parked here overnight."
            fluid
            :data-testid="`camera-context-${camera.id}`"
          />
        </label>
        <div
          v-if="contextChanged(camera)"
          class="panel-actions"
        >
          <Button
            label="Save context"
            text
            size="small"
            :loading="savingContext[camera.id]"
            :data-testid="`camera-context-save-${camera.id}`"
            @click="saveContext(camera)"
          />
        </div>
      </article>
    </div>
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

.panel-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
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

.camera-skeleton + .camera-skeleton {
  margin-top: 12px;
}

.camera-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.camera-row {
  padding: 16px;
  border-radius: 10px;
  background: var(--p-surface-50);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.blink-dark .camera-row {
  background: color-mix(in srgb, var(--p-surface-800) 55%, transparent);
}

.camera-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.camera-identity {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.camera-name {
  font-size: 0.92rem;
  font-weight: 600;
}

.camera-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
}

.muted {
  font-size: 0.78rem;
  color: var(--p-surface-500);
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field-label {
  font-size: 0.78rem;
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
</style>
