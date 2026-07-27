<script setup lang="ts">
import Button from "primevue/button";
import Message from "primevue/message";
import Skeleton from "primevue/skeleton";
import Tag from "primevue/tag";
import { useToast } from "primevue/usetoast";
import { onMounted, onUnmounted, reactive, ref } from "vue";
import { RouterLink } from "vue-router";

import {
  ApiError,
  cameraPreviewUrl,
  getSecurityFeedSettings,
  listCameras,
  recordCameraClip,
} from "@/api";
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
import { useFormatting } from "@/composables/useFormatting";
import { useBlinkStore } from "@/stores/blink";
import { useAuthStore } from "@/stores/auth";

import type { CameraRead, SecurityFeedSettingsRead } from "@/api";

const auth = useAuthStore();
const blink = useBlinkStore();
const toast = useToast();
const { formatRelativeTime } = useFormatting();

const loading = ref(true);
const loadError = ref("");
const cameras = ref<CameraRead[]>([]);
const feedSettings = ref<SecurityFeedSettingsRead | null>(null);

const tileVersion = reactive<Record<string, number>>({});
const tileError = reactive<Record<string, boolean>>({});
const tileUpdatedAt = reactive<Record<string, Date>>({});
const snapping = reactive<Record<string, boolean>>({});
const recording = reactive<Record<string, boolean>>({});

// Forces every "Xs ago" label to re-render on a shared 1s tick, without
// each tile needing its own timer.
const clock = ref(Date.now());
let clockTimer: ReturnType<typeof setInterval> | undefined;
let pollTimer: ReturnType<typeof setInterval> | undefined;

function visibleCameras(): CameraRead[] {
  // Only ever called once load() has populated feedSettings.value - see the
  // v-else-if/v-for template guards, all gated on loading being false.
  const selected = feedSettings.value!.camera_ids;
  if (selected.length === 0) {
    return cameras.value.filter((camera) => camera.enabled);
  }
  const byId = new Map(cameras.value.map((camera) => [camera.id, camera]));
  return selected.map((id) => byId.get(id)).filter((camera): camera is CameraRead => !!camera);
}

function tileSrc(camera: CameraRead): string {
  // bumpAllTiles() always seeds this before the grid (and thus any <img>) renders.
  const version = tileVersion[camera.id]!;
  return `${cameraPreviewUrl(camera.id)}?t=${version}`;
}

function onTileLoad(camera: CameraRead): void {
  tileError[camera.id] = false;
  tileUpdatedAt[camera.id] = new Date();
}

function onTileError(camera: CameraRead): void {
  tileError[camera.id] = true;
}

function bumpAllTiles(): void {
  for (const camera of visibleCameras()) {
    tileVersion[camera.id] = (tileVersion[camera.id] ?? 0) + 1;
  }
}

function startPolling(intervalSeconds: number): void {
  clearInterval(pollTimer);
  pollTimer = setInterval(bumpAllTiles, intervalSeconds * 1000);
}

async function snapNow(camera: CameraRead): Promise<void> {
  snapping[camera.id] = true;
  try {
    tileVersion[camera.id] = tileVersion[camera.id]! + 1;
    const base = cameraPreviewUrl(camera.id, { force: true });
    const img = new Image();
    img.src = `${base}&t=${tileVersion[camera.id]}`;
    await img.decode().catch(() => undefined);
    onTileLoad(camera);
  } finally {
    snapping[camera.id] = false;
  }
}

async function recordClipNow(camera: CameraRead): Promise<void> {
  recording[camera.id] = true;
  try {
    await recordCameraClip(camera.id);
    toast.add({
      severity: "success",
      summary: "Recording started",
      detail: `The clip will appear in your Library shortly (${camera.name}).`,
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
    recording[camera.id] = false;
  }
}

async function load(): Promise<void> {
  loading.value = true;
  loadError.value = "";
  try {
    await blink.refreshStatus();
    const [cameraList, settings] = await Promise.all([
      listCameras(),
      getSecurityFeedSettings(),
    ]);
    cameras.value = cameraList;
    feedSettings.value = settings;
    bumpAllTiles();
    startPolling(settings.refresh_interval_seconds);
  } catch (caught) {
    loadError.value = caught instanceof ApiError ? caught.message : "Could not load the security feed.";
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
  // pollTimer is only ever set once load() succeeds, so it can genuinely
  // still be undefined here (unmounted while loading, or after a load error).
  if (pollTimer) clearInterval(pollTimer);
  // clockTimer is always set synchronously in onMounted, before any unmount
  // can happen, so it needs no such guard.
  clearInterval(clockTimer);
});

function lastUpdatedLabel(camera: CameraRead): string {
  void clock.value;
  const updated = tileUpdatedAt[camera.id];
  return updated ? formatRelativeTime(updated) : "Loading…";
}
</script>

<template>
  <section>
    <PageHeader
      title="Security Feed"
      description="At-a-glance snapshots from your cameras, refreshed automatically."
    >
      <template
        v-if="auth.isAdmin"
        #actions
      >
        <RouterLink :to="{ name: 'settings', query: { tab: 'security-feed' } }">
          <Button
            label="Customize"
            icon="pi pi-sliders-h"
            severity="secondary"
            outlined
            data-testid="customize-feed"
          />
        </RouterLink>
      </template>
    </PageHeader>

    <div
      v-if="loading"
      class="feed-grid"
      data-testid="feed-loading"
    >
      <Skeleton
        v-for="n in 4"
        :key="n"
        height="220px"
        border-radius="14px"
      />
    </div>

    <Message
      v-else-if="loadError"
      severity="error"
      :closable="false"
      data-testid="feed-load-error"
    >
      {{ loadError }}
    </Message>

    <EmptyState
      v-else-if="!blink.isLinked"
      icon="pi pi-video"
      title="No Blink account linked"
      description="Link your Blink account in Settings to start seeing camera snapshots here."
      data-testid="feed-no-blink"
    />

    <EmptyState
      v-else-if="visibleCameras().length === 0"
      icon="pi pi-th-large"
      title="No cameras to show yet"
      description="Enable a camera in Settings > Cameras, or choose which ones appear here in Settings > Security Feed."
      data-testid="feed-empty"
    />

    <div
      v-else
      class="feed-grid"
      :style="{ '--feed-columns': feedSettings!.columns }"
      data-testid="feed-grid"
    >
      <article
        v-for="camera in visibleCameras()"
        :key="camera.id"
        class="feed-tile"
        :data-testid="`feed-tile-${camera.id}`"
      >
        <header class="tile-header">
          <span class="tile-name">{{ camera.name }}</span>
          <Tag
            v-if="!camera.enabled"
            severity="secondary"
            value="Paused"
          />
        </header>
        <div class="tile-image-wrap">
          <img
            :src="tileSrc(camera)"
            :alt="`Latest snapshot from ${camera.name}`"
            class="tile-image"
            @load="onTileLoad(camera)"
            @error="onTileError(camera)"
          >
          <div
            v-if="tileError[camera.id]"
            class="tile-overlay"
            data-testid="tile-error"
          >
            <i
              class="pi pi-exclamation-triangle"
              aria-hidden="true"
            />
            <span>Preview unavailable</span>
          </div>
        </div>
        <footer class="tile-footer">
          <span class="muted">{{ lastUpdatedLabel(camera) }}</span>
          <div class="tile-actions">
            <button
              v-if="auth.isAdmin"
              type="button"
              class="tile-action"
              :disabled="snapping[camera.id]"
              :data-testid="`snap-now-${camera.id}`"
              @click="snapNow(camera)"
            >
              <i class="pi pi-camera" /> Snap
            </button>
            <button
              v-if="auth.isAdmin"
              type="button"
              class="tile-action"
              :disabled="recording[camera.id]"
              :data-testid="`record-now-${camera.id}`"
              @click="recordClipNow(camera)"
            >
              <i class="pi pi-video" /> Record
            </button>
          </div>
        </footer>
      </article>
    </div>
  </section>
</template>

<style scoped>
.feed-grid {
  display: grid;
  grid-template-columns: repeat(var(--feed-columns, 2), minmax(0, 1fr));
  gap: 18px;
}

@media (max-width: 768px) {
  .feed-grid {
    grid-template-columns: 1fr;
  }
}

.feed-tile {
  display: flex;
  flex-direction: column;
  border-radius: 14px;
  overflow: hidden;
  border: 1px solid var(--p-surface-200);
  background: var(--p-surface-0);
}

.blink-dark .feed-tile {
  border-color: var(--p-surface-800);
  background: color-mix(in srgb, var(--p-surface-900) 60%, transparent);
}

.tile-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 12px 14px;
}

.tile-name {
  font-size: 0.92rem;
  font-weight: 700;
}

.tile-image-wrap {
  position: relative;
  aspect-ratio: 16 / 9;
  background: var(--p-surface-100);
}

.blink-dark .tile-image-wrap {
  background: var(--p-surface-950);
}

.tile-image {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.tile-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  font-size: 0.82rem;
  color: var(--p-surface-500);
  background: color-mix(in srgb, var(--p-surface-0) 85%, transparent);
}

.blink-dark .tile-overlay {
  background: color-mix(in srgb, var(--p-surface-950) 85%, transparent);
}

.tile-overlay i {
  font-size: 1.4rem;
  color: var(--p-orange-500);
}

.tile-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 14px;
  flex-wrap: wrap;
}

.muted {
  font-size: 0.78rem;
  color: var(--p-surface-500);
}

.tile-actions {
  display: flex;
  gap: 10px;
}

.tile-action {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: none;
  background: none;
  padding: 2px 0;
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--p-primary-600);
  cursor: pointer;
}

.blink-dark .tile-action {
  color: var(--p-primary-300);
}

.tile-action:disabled {
  opacity: 0.6;
  cursor: default;
}

.tile-action:hover:not(:disabled) {
  text-decoration: underline;
}
</style>
