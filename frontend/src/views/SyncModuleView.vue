<script setup lang="ts">
import Button from "primevue/button";
import Message from "primevue/message";
import Skeleton from "primevue/skeleton";
import Tag from "primevue/tag";
import ToggleSwitch from "primevue/toggleswitch";
import { useToast } from "primevue/usetoast";
import { onMounted, reactive, ref } from "vue";

import {
  ApiError,
  armSyncModule,
  bulkSetCameraMotionDetection,
  listSyncModuleCameras,
  listSyncModules,
  setCameraMotionDetection,
} from "@/api";
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
import SyncModuleLocalStorageBrowser from "@/components/SyncModuleLocalStorageBrowser.vue";
import { cameraModelLabel } from "@/lib/cameraModels";
import { useAuthStore } from "@/stores/auth";

import type { SyncModuleCameraRead, SyncModuleRead } from "@/api";

const toast = useToast();
const auth = useAuthStore();

const syncModules = ref<SyncModuleRead[]>([]);
const loading = ref(true);
const loadError = ref("");

const camerasBySyncModule = reactive<Record<string, SyncModuleCameraRead[]>>({});
const camerasLoading = reactive<Record<string, boolean>>({});
const camerasError = reactive<Record<string, string>>({});
const arming = reactive<Record<string, boolean>>({});
const bulkMotionWorking = reactive<Record<string, boolean>>({});
const motionWorking = reactive<Record<string, boolean>>({});

async function loadCamerasFor(syncModule: SyncModuleRead): Promise<void> {
  camerasLoading[syncModule.id] = true;
  camerasError[syncModule.id] = "";
  try {
    camerasBySyncModule[syncModule.id] = await listSyncModuleCameras(syncModule.id);
  } catch (caught) {
    camerasError[syncModule.id] =
      caught instanceof ApiError ? caught.message : "Could not load cameras.";
  } finally {
    camerasLoading[syncModule.id] = false;
  }
}

async function load(): Promise<void> {
  loading.value = true;
  loadError.value = "";
  try {
    syncModules.value = await listSyncModules();
    void Promise.all(syncModules.value.map((syncModule) => loadCamerasFor(syncModule)));
  } catch (caught) {
    loadError.value =
      caught instanceof ApiError ? caught.message : "Could not load sync modules.";
  } finally {
    loading.value = false;
  }
}

onMounted(load);

function replaceSyncModule(updated: SyncModuleRead): void {
  // load() always populates the full list before any card can render, so
  // the entry being replaced is always still present.
  const index = syncModules.value.findIndex((s) => s.id === updated.id);
  // eslint-disable-next-line security/detect-object-injection
  syncModules.value[index] = updated;
}

async function toggleArmed(syncModule: SyncModuleRead): Promise<void> {
  arming[syncModule.id] = true;
  try {
    const updated = await armSyncModule(syncModule.id, !syncModule.armed);
    replaceSyncModule(updated);
    toast.add({
      severity: "success",
      summary: updated.armed ? `${updated.name} armed` : `${updated.name} disarmed`,
      life: 2500,
    });
  } catch (caught) {
    toast.add({
      severity: "error",
      summary: "Could not change armed state",
      detail: caught instanceof ApiError ? caught.message : "Unexpected error.",
      life: 4000,
    });
  } finally {
    arming[syncModule.id] = false;
  }
}

function replaceCamera(syncModuleId: string, updated: SyncModuleCameraRead): void {
  // syncModuleId always comes from our own loaded sync-module list, never
  // external input.
  // eslint-disable-next-line security/detect-object-injection
  const cameras = camerasBySyncModule[syncModuleId];
  const index = cameras.findIndex((c) => c.camera_id === updated.camera_id);
  // eslint-disable-next-line security/detect-object-injection
  cameras[index] = updated;
}

async function toggleCameraMotion(
  syncModule: SyncModuleRead,
  camera: SyncModuleCameraRead,
  enabled: boolean,
): Promise<void> {
  motionWorking[camera.camera_id] = true;
  try {
    const updated = await setCameraMotionDetection(syncModule.id, camera.camera_id, enabled);
    replaceCamera(syncModule.id, updated);
  } catch (caught) {
    toast.add({
      severity: "error",
      summary: "Could not update motion detection",
      detail: caught instanceof ApiError ? caught.message : "Unexpected error.",
      life: 4000,
    });
  } finally {
    motionWorking[camera.camera_id] = false;
  }
}

async function bulkSetMotion(syncModule: SyncModuleRead, enabled: boolean): Promise<void> {
  bulkMotionWorking[syncModule.id] = true;
  try {
    const result = await bulkSetCameraMotionDetection(syncModule.id, enabled);
    toast.add({
      severity: result.failed > 0 ? "warn" : "success",
      summary: `${enabled ? "Enabled" : "Disabled"} motion on ${result.succeeded} camera(s)`,
      detail: result.failed > 0 ? `${result.failed} could not be updated.` : undefined,
      life: 3500,
    });
    await loadCamerasFor(syncModule);
  } catch (caught) {
    toast.add({
      severity: "error",
      summary: "Bulk motion update failed",
      detail: caught instanceof ApiError ? caught.message : "Unexpected error.",
      life: 4000,
    });
  } finally {
    bulkMotionWorking[syncModule.id] = false;
  }
}

function armStateLabel(syncModule: SyncModuleRead): string {
  if (syncModule.armed === null) return "Unknown";
  return syncModule.armed ? "Armed" : "Disarmed";
}

function armStateClass(syncModule: SyncModuleRead): string {
  if (syncModule.armed === null) return "arm-unknown";
  return syncModule.armed ? "arm-armed" : "arm-disarmed";
}

function localStorageUnavailableReason(syncModule: SyncModuleRead): string {
  if (!syncModule.is_physical_hub) {
    return "This network has no physical Sync Module, so there's no USB storage to browse.";
  }
  return "This Sync Module doesn't support local USB storage.";
}
</script>

<template>
  <section>
    <PageHeader
      title="Sync Module"
      description="Arm or disarm, control motion detection per camera, and browse clips stored on an attached USB drive."
    />

    <div
      v-if="loading"
      class="cards"
      data-testid="sync-modules-loading"
    >
      <Skeleton
        height="360px"
        border-radius="14px"
      />
    </div>

    <EmptyState
      v-else-if="loadError"
      icon="pi pi-exclamation-triangle"
      title="Couldn't load Sync Modules"
      description="We weren't able to reach the server. Check your connection and try again."
      data-testid="sync-modules-load-error"
    >
      <template #actions>
        <Button
          label="Retry"
          icon="pi pi-refresh"
          severity="secondary"
          outlined
          data-testid="retry-sync-modules"
          @click="load"
        />
      </template>
    </EmptyState>

    <EmptyState
      v-else-if="syncModules.length === 0"
      icon="pi pi-shield"
      title="No Sync Modules found"
      description="Link your Blink account and sync at least once, and any Sync Modules on your account will show up here."
      data-testid="sync-modules-empty"
    />

    <div
      v-else
      class="cards"
    >
      <article
        v-for="syncModule in syncModules"
        :key="syncModule.id"
        class="sync-module-card"
        :data-testid="`sync-module-card-${syncModule.id}`"
      >
        <div class="card-header">
          <div class="identity">
            <span class="sync-module-name">{{ syncModule.name }}</span>
            <Tag
              :value="syncModule.online ? 'Online' : 'Offline'"
              :severity="syncModule.online ? 'success' : 'danger'"
            />
            <Tag
              v-if="!syncModule.is_physical_hub"
              value="No physical hub"
              severity="secondary"
            />
          </div>
          <span
            v-if="syncModule.serial || syncModule.firmware_version"
            class="muted"
          >
            <template v-if="syncModule.serial">Serial: {{ syncModule.serial }}</template>
            <template v-if="syncModule.serial && syncModule.firmware_version"> · </template>
            <template v-if="syncModule.firmware_version">
              Firmware: {{ syncModule.firmware_version }}
            </template>
          </span>
        </div>

        <div
          class="arm-panel"
          :class="armStateClass(syncModule)"
          :data-testid="`arm-panel-${syncModule.id}`"
        >
          <div class="arm-status">
            <i
              class="pi pi-shield arm-icon"
              aria-hidden="true"
            />
            <div>
              <span
                class="arm-state-label"
                :data-testid="`arm-state-${syncModule.id}`"
              >{{ armStateLabel(syncModule) }}</span>
              <span class="arm-hint">{{ syncModule.camera_count }} camera(s) on this network</span>
            </div>
          </div>
          <Button
            v-if="auth.isAdmin"
            :label="syncModule.armed ? 'Disarm' : 'Arm'"
            :severity="syncModule.armed ? 'secondary' : 'success'"
            :loading="arming[syncModule.id]"
            :data-testid="`arm-toggle-${syncModule.id}`"
            @click="toggleArmed(syncModule)"
          />
        </div>

        <div class="motion-section">
          <div class="motion-header">
            <h4>Motion detection</h4>
            <div
              v-if="auth.isAdmin"
              class="motion-bulk-actions"
            >
              <Button
                label="Enable all"
                size="small"
                outlined
                :loading="bulkMotionWorking[syncModule.id]"
                :data-testid="`motion-enable-all-${syncModule.id}`"
                @click="bulkSetMotion(syncModule, true)"
              />
              <Button
                label="Disable all"
                size="small"
                outlined
                severity="secondary"
                :loading="bulkMotionWorking[syncModule.id]"
                :data-testid="`motion-disable-all-${syncModule.id}`"
                @click="bulkSetMotion(syncModule, false)"
              />
            </div>
          </div>

          <!-- loadCamerasFor sets camerasLoading[id]=true synchronously before
          any await, so by the time this card first renders it's already
          true - camerasBySyncModule[id] is only ever read once loading has
          gone false, by which point the fetch has already populated it. -->
          <Skeleton
            v-if="camerasLoading[syncModule.id]"
            height="60px"
            :data-testid="`cameras-loading-${syncModule.id}`"
          />
          <Message
            v-else-if="camerasError[syncModule.id]"
            severity="error"
            :closable="false"
            :data-testid="`cameras-error-${syncModule.id}`"
          >
            {{ camerasError[syncModule.id] }}
          </Message>
          <p
            v-else-if="camerasBySyncModule[syncModule.id]!.length === 0"
            class="muted"
            :data-testid="`cameras-empty-${syncModule.id}`"
          >
            No cameras on this network yet.
          </p>
          <ul
            v-else
            class="camera-motion-list"
            :data-testid="`camera-motion-list-${syncModule.id}`"
          >
            <li
              v-for="camera in camerasBySyncModule[syncModule.id]"
              :key="camera.camera_id"
              class="camera-motion-row"
              :data-testid="`camera-motion-row-${camera.camera_id}`"
            >
              <div class="camera-motion-identity">
                <span class="camera-name">{{ camera.name }}</span>
                <Tag
                  :value="cameraModelLabel(camera.camera_type)"
                  severity="secondary"
                />
              </div>
              <ToggleSwitch
                v-if="auth.isAdmin"
                v-tooltip.top="
                  camera.motion_supported
                    ? undefined
                    : 'Mini cameras follow the Sync Module\'s armed state.'
                "
                :model-value="camera.motion_enabled"
                :disabled="!camera.motion_supported || motionWorking[camera.camera_id]"
                :data-testid="`camera-motion-${camera.camera_id}`"
                @update:model-value="(v: boolean) => toggleCameraMotion(syncModule, camera, v)"
              />
              <Tag
                v-else
                :value="camera.motion_enabled ? 'Motion on' : 'Motion off'"
                :severity="camera.motion_enabled ? 'success' : 'secondary'"
              />
            </li>
          </ul>
        </div>

        <SyncModuleLocalStorageBrowser
          v-if="syncModule.is_physical_hub && syncModule.local_storage_compatible"
          :sync-module-id="syncModule.id"
        />
        <p
          v-else
          class="muted local-storage-unsupported"
          :data-testid="`local-storage-unsupported-${syncModule.id}`"
        >
          {{ localStorageUnavailableReason(syncModule) }}
        </p>
      </article>
    </div>
  </section>
</template>

<style scoped>
.cards {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.sync-module-card {
  padding: 20px 22px;
  border-radius: 14px;
  border: 1px solid var(--p-surface-200);
  background: var(--p-surface-0);
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.blink-dark .sync-module-card {
  border-color: var(--p-surface-800);
  background: color-mix(in srgb, var(--p-surface-900) 60%, transparent);
}

.card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.identity {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.sync-module-name {
  font-size: 0.95rem;
  font-weight: 700;
}

.muted {
  font-size: 0.82rem;
  color: var(--p-surface-500);
  margin: 0;
}

.arm-panel {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 20px;
  border-radius: 12px;
  flex-wrap: wrap;
}

.arm-status {
  display: flex;
  align-items: center;
  gap: 14px;
}

.arm-icon {
  font-size: 1.6rem;
}

.arm-state-label {
  display: block;
  font-size: 1.3rem;
  font-weight: 800;
  letter-spacing: 0.02em;
}

.arm-hint {
  display: block;
  font-size: 0.8rem;
  opacity: 0.8;
}

.arm-armed {
  background: color-mix(in srgb, var(--p-green-500) 16%, transparent);
  color: var(--p-green-700);
}

.blink-dark .arm-armed {
  color: var(--p-green-300);
}

.arm-disarmed {
  background: var(--p-surface-100);
  color: var(--p-surface-600);
}

.blink-dark .arm-disarmed {
  background: color-mix(in srgb, var(--p-surface-800) 70%, transparent);
  color: var(--p-surface-300);
}

.arm-unknown {
  background: color-mix(in srgb, var(--p-yellow-500) 16%, transparent);
  color: var(--p-yellow-700);
}

.blink-dark .arm-unknown {
  color: var(--p-yellow-300);
}

.motion-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.motion-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.motion-header h4 {
  margin: 0;
  font-size: 0.8rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  color: var(--p-surface-500);
}

.motion-bulk-actions {
  display: flex;
  gap: 8px;
}

.camera-motion-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.camera-motion-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  border-radius: 10px;
  background: var(--p-surface-50);
}

.blink-dark .camera-motion-row {
  background: color-mix(in srgb, var(--p-surface-800) 55%, transparent);
}

.camera-motion-identity {
  display: flex;
  align-items: center;
  gap: 10px;
}

.camera-name {
  font-size: 0.88rem;
  font-weight: 600;
}

.local-storage-unsupported {
  padding-top: 4px;
}
</style>
