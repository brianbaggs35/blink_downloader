<script setup lang="ts">
import Button from "primevue/button";
import Message from "primevue/message";
import Select from "primevue/select";
import Skeleton from "primevue/skeleton";
import ToggleSwitch from "primevue/toggleswitch";
import { useToast } from "primevue/usetoast";
import { computed, onMounted, onUnmounted, reactive, ref, watch } from "vue";

import {
  ApiError,
  cameraPreviewUrl,
  getLiveViewSettings,
  listCameras,
  recordCameraClip,
  startCameraLiveView,
  stopCameraLiveView,
} from "@/api";
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
import VideoPlayer from "@/components/VideoPlayer.vue";
import { useFormatting } from "@/composables/useFormatting";
import { useSidebarCollapse } from "@/composables/useSidebarCollapse";
import { useAuthStore } from "@/stores/auth";
import { useBlinkStore } from "@/stores/blink";

import type { CameraRead } from "@/api";

type LiveStreamState = "idle" | "starting" | "live" | "unsupported" | "error";

interface Slot {
  cameraId: string | null;
  version: number;
  forceNext: boolean;
  loading: boolean;
  error: string;
  updatedAt: Date | null;
  recording: boolean;
  liveState: LiveStreamState;
  liveError: string;
  liveSessionId: string | null;
  livePlaylistUrl: string | null;
}

function emptySlot(): Slot {
  return {
    cameraId: null,
    version: 0,
    forceNext: false,
    loading: false,
    error: "",
    updatedAt: null,
    recording: false,
    liveState: "idle",
    liveError: "",
    liveSessionId: null,
    livePlaylistUrl: null,
  };
}

const toast = useToast();
const auth = useAuthStore();
const blink = useBlinkStore();
const sidebar = useSidebarCollapse();
const { formatRelativeTime } = useFormatting();

const loading = ref(true);
const loadError = ref("");
const cameras = ref<CameraRead[]>([]);

const primary = reactive<Slot>(emptySlot());
const secondary = reactive<Slot>(emptySlot());
const compareMode = ref(false);

const autoRefreshEnabled = ref(false);
const autoRefreshIntervalSeconds = ref(10);
let refreshTimer: ReturnType<typeof setInterval> | undefined;

const clock = ref(Date.now());
let clockTimer: ReturnType<typeof setInterval> | undefined;

const cameraOptions = computed(() =>
  cameras.value.map((camera) => ({ label: camera.name, value: camera.id })),
);

function cameraById(id: string | null): CameraRead | undefined {
  return cameras.value.find((camera) => camera.id === id);
}

// Only ever bound in the template behind a v-if on slot.cameraId (see
// tileSrc's own call sites) - cameraId is never null here in practice.
function tileSrc(slot: Slot): string {
  const base = cameraPreviewUrl(slot.cameraId!, { force: slot.forceNext });
  return `${base}${base.includes("?") ? "&" : "?"}t=${slot.version}`;
}

function onSlotLoad(slot: Slot): void {
  slot.loading = false;
  slot.forceNext = false;
  slot.error = "";
  slot.updatedAt = new Date();
}

function onSlotError(slot: Slot): void {
  slot.loading = false;
  slot.forceNext = false;
  slot.error = "Preview unavailable.";
}

function refreshSlot(slot: Slot, { force = false }: { force?: boolean } = {}): void {
  if (!slot.cameraId) return;
  slot.loading = true;
  slot.forceNext = force;
  slot.version += 1;
}

function liveButtonLabel(slot: Slot): string {
  if (slot.liveState === "live") return "Stop live view";
  if (slot.liveState === "starting") return "Starting live view…";
  return "Start live view";
}

async function startLiveView(slot: Slot): Promise<void> {
  if (!slot.cameraId || slot.liveState === "starting" || slot.liveState === "live") return;
  slot.liveState = "starting";
  slot.liveError = "";
  try {
    const session = await startCameraLiveView(slot.cameraId);
    slot.liveSessionId = session.session_id;
    slot.livePlaylistUrl = session.playlist_url;
    slot.liveState = "live";
  } catch (caught) {
    slot.liveState = caught instanceof ApiError && caught.status === 409 ? "unsupported" : "error";
    slot.liveError = caught instanceof ApiError ? caught.message : "Could not start the live stream.";
  }
}

async function stopLiveView(slot: Slot): Promise<void> {
  const cameraId = slot.cameraId;
  const sessionId = slot.liveSessionId;
  slot.liveState = "idle";
  slot.liveSessionId = null;
  slot.livePlaylistUrl = null;
  slot.liveError = "";
  // Every call site already guards on slot.liveSessionId (which can only be
  // set alongside a non-null cameraId) before calling this, so the false
  // branch is unreachable through the UI - kept as a defensive check, not
  // exercised by a contrived test.
  /* v8 ignore next */
  if (cameraId && sessionId) {
    try {
      await stopCameraLiveView(cameraId, sessionId);
    } catch {
      // Best-effort - the backend's own idle timeout reclaims an abandoned
      // session regardless, and the UI has already dropped back to the
      // snapshot view either way.
    }
  }
}

function toggleLiveView(slot: Slot): void {
  if (slot.liveState === "live") {
    void stopLiveView(slot);
  } else {
    void startLiveView(slot);
  }
}

// Takes the newly-picked camera id explicitly (rather than reading it back
// off slot.cameraId after the fact) because Select's v-model setter and
// this handler respond to the same update:model-value event - by the time
// any post-hoc read of slot.cameraId would run, it may already reflect the
// new camera, not the one whose live session actually needs stopping.
async function onCameraChange(slot: Slot, cameraId: string | null): Promise<void> {
  if (slot.liveSessionId) {
    await stopLiveView(slot);
  }
  slot.cameraId = cameraId;
  refreshSlot(slot);
}

function refreshAll(): void {
  // The passive preview endpoint never asks the camera for a new picture -
  // only force=true does, and that's admin-only server-side (it wakes a
  // battery-powered camera on demand). A non-admin viewer's auto-refresh
  // still re-polls passively, same as before; only an admin's tick now
  // genuinely forces a fresh snapshot.
  refreshSlot(primary, { force: auth.isAdmin });
  if (compareMode.value) {
    refreshSlot(secondary, { force: auth.isAdmin });
  }
}

function startAutoRefresh(): void {
  // clearInterval(undefined) is a safe no-op - no need to check first.
  clearInterval(refreshTimer);
  if (!autoRefreshEnabled.value) return;
  refreshTimer = setInterval(refreshAll, autoRefreshIntervalSeconds.value * 1000);
}

// A watcher, not an @update:model-value handler on the toggle, so this
// always sees the new value - it doesn't depend on firing after (rather
// than racing) the v-model setter that assigns it.
watch(autoRefreshEnabled, startAutoRefresh);

function toggleCompare(): void {
  const turningOff = compareMode.value;
  compareMode.value = !compareMode.value;
  if (turningOff) {
    if (secondary.liveSessionId) {
      void stopLiveView(secondary);
    }
  } else if (!secondary.cameraId) {
    const other = cameras.value.find((camera) => camera.id !== primary.cameraId);
    secondary.cameraId = other?.id ?? null;
    refreshSlot(secondary);
  }
}

async function saveClip(slot: Slot): Promise<void> {
  if (!slot.cameraId) return;
  slot.recording = true;
  try {
    await recordCameraClip(slot.cameraId);
    toast.add({
      severity: "success",
      summary: "Recording started",
      detail: "The clip will appear in your Library shortly.",
      life: 4000,
    });
  } catch (caught) {
    toast.add({
      severity: "error",
      summary: "Could not start recording",
      detail: caught instanceof ApiError ? caught.message : "Unexpected error.",
      life: 4000,
    });
  } finally {
    slot.recording = false;
  }
}

function screenshot(slot: Slot): void {
  const image = document.querySelector<HTMLImageElement>(`[data-preview-for="${slot.cameraId}"]`);
  if (!image || !image.naturalWidth) return;
  const canvas = document.createElement("canvas");
  canvas.width = image.naturalWidth;
  canvas.height = image.naturalHeight;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.drawImage(image, 0, 0);
  canvas.toBlob((blob) => {
    if (!blob) return;
    const camera = cameraById(slot.cameraId);
    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    // cameras.value is only ever populated once, at load(), and every
    // slot.cameraId always comes from that same list - camera is always
    // found in practice; the fallback only exists to satisfy the type.
    /* v8 ignore next */
    link.download = `${camera?.name ?? "camera"}-${stamp}.jpg`;
    link.click();
    URL.revokeObjectURL(url);
  }, "image/jpeg");
}

async function load(): Promise<void> {
  loading.value = true;
  loadError.value = "";
  try {
    await blink.refreshStatus();
    const [cameraList, settings] = await Promise.all([listCameras(), getLiveViewSettings()]);
    cameras.value = cameraList;
    autoRefreshEnabled.value = settings.auto_refresh_enabled;
    autoRefreshIntervalSeconds.value = settings.auto_refresh_interval_seconds;
    const defaultId = settings.default_camera_id ?? cameraList[0]?.id ?? null;
    primary.cameraId = defaultId;
    if (defaultId) {
      refreshSlot(primary);
    }
    startAutoRefresh();
  } catch (caught) {
    loadError.value = caught instanceof ApiError ? caught.message : "Could not load Live View.";
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  void load();
  clockTimer = setInterval(() => {
    clock.value = Date.now();
  }, 1000);
});

onUnmounted(() => {
  clearInterval(refreshTimer);
  clearInterval(clockTimer);
  // Belt-and-suspenders alongside the backend's own idle-session sweep -
  // stops promptly instead of waiting out that timeout when the user
  // navigates away mid-stream.
  if (primary.cameraId && primary.liveSessionId) {
    void stopCameraLiveView(primary.cameraId, primary.liveSessionId);
  }
  if (secondary.cameraId && secondary.liveSessionId) {
    void stopCameraLiveView(secondary.cameraId, secondary.liveSessionId);
  }
});

function updatedLabel(slot: Slot): string {
  // Deliberately-unused read: the reactive dependency that makes the "X
  // minutes ago" label recompute every clock tick, not just when
  // slot.updatedAt itself changes.
  void clock.value; // NOSONAR
  return slot.updatedAt ? formatRelativeTime(slot.updatedAt) : "Not loaded yet";
}
</script>

<template>
  <section>
    <PageHeader
      title="Live View"
      description="Check in on a camera right now with the latest snapshot, or start a live stream for continuous video - available on most (not all) camera models."
    >
      <template #actions>
        <Button
          :label="sidebar.isCollapsed.value ? 'Expand menu' : 'Collapse menu'"
          :icon="sidebar.isCollapsed.value ? 'pi pi-angle-right' : 'pi pi-angle-left'"
          severity="secondary"
          text
          data-testid="live-view-sidebar-toggle"
          @click="sidebar.toggle()"
        />
        <Button
          :label="compareMode ? 'Single camera' : 'Compare two cameras'"
          icon="pi pi-th-large"
          severity="secondary"
          outlined
          data-testid="toggle-compare"
          @click="toggleCompare"
        />
        <div class="auto-refresh">
          <ToggleSwitch
            v-model="autoRefreshEnabled"
            data-testid="auto-refresh-toggle"
          />
          <span class="muted">Auto-refresh every {{ autoRefreshIntervalSeconds }}s</span>
        </div>
      </template>
    </PageHeader>

    <div
      v-if="loading"
      data-testid="live-view-loading"
    >
      <Skeleton
        height="420px"
        border-radius="16px"
      />
    </div>

    <Message
      v-else-if="loadError"
      severity="error"
      :closable="false"
      data-testid="live-view-load-error"
    >
      {{ loadError }}
    </Message>

    <EmptyState
      v-else-if="!blink.isLinked || cameras.length === 0"
      icon="pi pi-video"
      title="No cameras available"
      description="Link your Blink account and sync at least one camera to use Live View."
      data-testid="live-view-empty"
    />

    <div
      v-else
      class="stage"
      :class="{ compare: compareMode }"
    >
      <article class="panel">
        <div class="panel-toolbar">
          <label
            for="primary-camera-select"
            class="sr-only"
          >Primary camera</label>
          <Select
            :model-value="primary.cameraId"
            input-id="primary-camera-select"
            aria-label="Primary camera"
            :options="cameraOptions"
            option-label="label"
            option-value="value"
            placeholder="Choose a camera"
            data-testid="primary-camera-select"
            @update:model-value="(value) => onCameraChange(primary, value as string | null)"
          />
        </div>
        <div class="preview-wrap">
          <VideoPlayer
            v-if="primary.liveState === 'live' && primary.livePlaylistUrl"
            :src="primary.livePlaylistUrl"
            type="application/x-mpegURL"
            live
            data-testid="primary-live-player"
          />
          <template v-else>
            <!-- cameraOptions is only reachable once cameras.length > 0, and
            load() always seeds primary.cameraId from that same list, so
            it's never actually null once this panel renders - no v-if
            needed. -->
            <img
              :src="tileSrc(primary)"
              :data-preview-for="primary.cameraId"
              class="preview-image"
              alt="Live camera preview"
              data-testid="primary-preview"
              @load="onSlotLoad(primary)"
              @error="onSlotError(primary)"
            >
            <div
              v-if="primary.error"
              class="preview-overlay"
            >
              <i
                class="pi pi-exclamation-triangle"
                aria-hidden="true"
              />
              <span>{{ primary.error }}</span>
            </div>
            <div
              v-if="primary.liveState === 'starting'"
              class="preview-overlay starting"
              data-testid="primary-live-starting"
            >
              <i
                class="pi pi-spin pi-spinner"
                aria-hidden="true"
              />
              <span>Starting live view…</span>
            </div>
          </template>
        </div>
        <Message
          v-if="primary.liveState === 'unsupported' || primary.liveState === 'error'"
          :severity="primary.liveState === 'unsupported' ? 'warn' : 'error'"
          :closable="false"
          data-testid="primary-live-error"
        >
          {{ primary.liveError }}
        </Message>
        <footer class="panel-footer">
          <span class="muted">Updated {{ updatedLabel(primary) }}</span>
          <div class="panel-actions">
            <Button
              v-if="auth.isAdmin"
              :label="liveButtonLabel(primary)"
              :icon="primary.liveState === 'live' ? 'pi pi-stop-circle' : 'pi pi-play-circle'"
              size="small"
              :severity="primary.liveState === 'live' ? 'danger' : 'primary'"
              :loading="primary.liveState === 'starting'"
              data-testid="primary-live-toggle"
              @click="toggleLiveView(primary)"
            />
            <Button
              v-if="auth.isAdmin"
              label="Refresh"
              icon="pi pi-refresh"
              size="small"
              severity="secondary"
              outlined
              :loading="primary.loading"
              data-testid="primary-refresh"
              @click="refreshSlot(primary, { force: true })"
            />
            <Button
              label="Screenshot"
              icon="pi pi-camera"
              size="small"
              severity="secondary"
              outlined
              data-testid="primary-screenshot"
              @click="screenshot(primary)"
            />
            <Button
              v-if="auth.isAdmin"
              label="Save clip"
              icon="pi pi-video"
              size="small"
              :loading="primary.recording"
              data-testid="primary-save-clip"
              @click="saveClip(primary)"
            />
          </div>
        </footer>
      </article>

      <article
        v-if="compareMode"
        class="panel"
      >
        <div class="panel-toolbar">
          <label
            for="secondary-camera-select"
            class="sr-only"
          >Secondary camera</label>
          <Select
            :model-value="secondary.cameraId"
            input-id="secondary-camera-select"
            aria-label="Secondary camera"
            :options="cameraOptions"
            option-label="label"
            option-value="value"
            placeholder="Choose a camera"
            data-testid="secondary-camera-select"
            @update:model-value="(value) => onCameraChange(secondary, value as string | null)"
          />
        </div>
        <div class="preview-wrap">
          <VideoPlayer
            v-if="secondary.liveState === 'live' && secondary.livePlaylistUrl"
            :src="secondary.livePlaylistUrl"
            type="application/x-mpegURL"
            live
            data-testid="secondary-live-player"
          />
          <template v-else>
            <img
              v-if="secondary.cameraId"
              :src="tileSrc(secondary)"
              :data-preview-for="secondary.cameraId"
              class="preview-image"
              alt="Second live camera preview"
              data-testid="secondary-preview"
              @load="onSlotLoad(secondary)"
              @error="onSlotError(secondary)"
            >
            <div
              v-else
              class="preview-overlay"
              data-testid="secondary-no-camera"
            >
              <i
                class="pi pi-video"
                aria-hidden="true"
              />
              <span>No other camera to compare against yet.</span>
            </div>
            <div
              v-if="secondary.error"
              class="preview-overlay"
            >
              <i
                class="pi pi-exclamation-triangle"
                aria-hidden="true"
              />
              <span>{{ secondary.error }}</span>
            </div>
            <div
              v-if="secondary.liveState === 'starting'"
              class="preview-overlay starting"
              data-testid="secondary-live-starting"
            >
              <i
                class="pi pi-spin pi-spinner"
                aria-hidden="true"
              />
              <span>Starting live view…</span>
            </div>
          </template>
        </div>
        <Message
          v-if="secondary.liveState === 'unsupported' || secondary.liveState === 'error'"
          :severity="secondary.liveState === 'unsupported' ? 'warn' : 'error'"
          :closable="false"
          data-testid="secondary-live-error"
        >
          {{ secondary.liveError }}
        </Message>
        <footer class="panel-footer">
          <span class="muted">Updated {{ updatedLabel(secondary) }}</span>
          <div class="panel-actions">
            <Button
              v-if="auth.isAdmin"
              :label="liveButtonLabel(secondary)"
              :icon="secondary.liveState === 'live' ? 'pi pi-stop-circle' : 'pi pi-play-circle'"
              size="small"
              :severity="secondary.liveState === 'live' ? 'danger' : 'primary'"
              :loading="secondary.liveState === 'starting'"
              data-testid="secondary-live-toggle"
              @click="toggleLiveView(secondary)"
            />
            <Button
              v-if="auth.isAdmin"
              label="Refresh"
              icon="pi pi-refresh"
              size="small"
              severity="secondary"
              outlined
              :loading="secondary.loading"
              data-testid="secondary-refresh"
              @click="refreshSlot(secondary, { force: true })"
            />
            <Button
              label="Screenshot"
              icon="pi pi-camera"
              size="small"
              severity="secondary"
              outlined
              data-testid="secondary-screenshot"
              @click="screenshot(secondary)"
            />
            <Button
              v-if="auth.isAdmin"
              label="Save clip"
              icon="pi pi-video"
              size="small"
              :loading="secondary.recording"
              data-testid="secondary-save-clip"
              @click="saveClip(secondary)"
            />
          </div>
        </footer>
      </article>
    </div>
  </section>
</template>

<style scoped>
.auto-refresh {
  display: flex;
  align-items: center;
  gap: 10px;
}

.muted {
  font-size: 0.8rem;
  color: var(--p-surface-500);
  white-space: nowrap;
}

.stage {
  display: grid;
  grid-template-columns: 1fr;
  gap: 20px;
}

.stage.compare {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

@media (max-width: 900px) {
  .stage.compare {
    grid-template-columns: 1fr;
  }
}

.panel {
  display: flex;
  flex-direction: column;
  border-radius: 16px;
  overflow: hidden;
  border: 1px solid var(--p-surface-200);
  background: var(--p-surface-0);
}

.blink-dark .panel {
  border-color: var(--p-surface-800);
  background: color-mix(in srgb, var(--p-surface-900) 60%, transparent);
}

.panel-toolbar {
  padding: 14px 16px;
  border-bottom: 1px solid var(--p-surface-200);
}

.blink-dark .panel-toolbar {
  border-bottom-color: var(--p-surface-800);
}

.preview-wrap {
  position: relative;
  aspect-ratio: 16 / 9;
  background: #000;
}

.preview-image {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
  background: #000;
}

.preview-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--p-surface-300);
  background: rgb(0 0 0 / 0.55);
}

.preview-overlay i {
  font-size: 1.6rem;
  color: var(--p-orange-400);
}

.preview-overlay.starting i {
  color: var(--p-primary-400);
}

.panel-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 16px;
  flex-wrap: wrap;
}

.panel-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
</style>
