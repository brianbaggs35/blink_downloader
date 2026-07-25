<script setup lang="ts">
import Checkbox from "primevue/checkbox";
import { ref } from "vue";

import { clipThumbnailUrl } from "@/api";
import { useFormatting } from "@/composables/useFormatting";

import type { ClipRead } from "@/api";

const props = withDefaults(
  defineProps<{
    clip: ClipRead;
    cameraName: string;
    selected: boolean;
    selectable?: boolean;
  }>(),
  { selectable: true },
);

const emit = defineEmits<{
  open: [];
  "update:selected": [value: boolean];
}>();

const { formatDateTime, formatDuration } = useFormatting();

const thumbnailFailed = ref(false);

function onCheckboxClick(event: Event): void {
  event.stopPropagation();
}
</script>

<template>
  <article
    class="card"
    :class="{ selected }"
    data-testid="clip-card"
    @click="emit('open')"
  >
    <div
      v-if="selectable"
      class="checkbox-overlay"
      @click="onCheckboxClick"
    >
      <Checkbox
        :model-value="selected"
        binary
        data-testid="clip-select"
        @update:model-value="(v: boolean) => emit('update:selected', v)"
      />
    </div>

    <div class="thumb">
      <img
        v-if="props.clip.thumbnail_generated && !thumbnailFailed"
        :src="clipThumbnailUrl(props.clip.id)"
        :alt="`Thumbnail for clip on ${cameraName}`"
        loading="lazy"
        @error="thumbnailFailed = true"
      >
      <div
        v-else
        class="thumb-fallback"
      >
        <i
          class="pi pi-video"
          aria-hidden="true"
        />
      </div>
      <span
        v-if="props.clip.duration_seconds !== null"
        class="duration-badge"
      >
        {{ formatDuration(props.clip.duration_seconds) }}
      </span>
      <span
        v-if="!props.clip.downloaded_at"
        class="pending-badge"
      >Downloading…</span>
    </div>

    <div class="meta">
      <p class="camera-name">
        {{ cameraName }}
      </p>
      <p class="recorded-at">
        {{ formatDateTime(props.clip.recorded_at) }}
      </p>
    </div>
  </article>
</template>

<style scoped>
.card {
  position: relative;
  border-radius: 12px;
  border: 1px solid var(--p-surface-200);
  background: var(--p-surface-0);
  overflow: hidden;
  cursor: pointer;
  transition:
    border-color 0.15s ease,
    box-shadow 0.15s ease,
    transform 0.15s ease;
}

.blink-dark .card {
  border-color: var(--p-surface-800);
  background: color-mix(in srgb, var(--p-surface-900) 55%, transparent);
}

.card:hover {
  border-color: var(--p-primary-400);
  transform: translateY(-3px);
  box-shadow: 0 10px 24px -12px color-mix(in srgb, var(--p-surface-950) 60%, transparent);
}

.card:hover .checkbox-overlay {
  opacity: 1;
}

.card.selected {
  border-color: var(--p-primary-500);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--p-primary-500) 35%, transparent);
}

.checkbox-overlay {
  position: absolute;
  top: 8px;
  left: 8px;
  z-index: 2;
  padding: 4px;
  border-radius: 6px;
  background: color-mix(in srgb, var(--p-surface-950) 55%, transparent);
  backdrop-filter: blur(4px);
  opacity: 0.75;
  transition: opacity 0.15s ease;
}

.card.selected .checkbox-overlay {
  opacity: 1;
}

.thumb {
  position: relative;
  aspect-ratio: 16 / 9;
  background: var(--p-surface-100);
}

.blink-dark .thumb {
  background: var(--p-surface-800);
}

.thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.thumb-fallback {
  width: 100%;
  height: 100%;
  display: grid;
  place-items: center;
}

.thumb-fallback i {
  font-size: 1.6rem;
  color: var(--p-surface-400);
}

.duration-badge,
.pending-badge {
  position: absolute;
  bottom: 8px;
  right: 8px;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 0.72rem;
  font-weight: 600;
  color: white;
  background: color-mix(in srgb, var(--p-surface-950) 65%, transparent);
  backdrop-filter: blur(4px);
}

.pending-badge {
  left: 8px;
  right: auto;
  background: color-mix(in srgb, var(--p-primary-600) 75%, transparent);
  animation: pending-pulse 1.8s ease-in-out infinite;
}

@keyframes pending-pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.55;
  }
}

.meta {
  padding: 10px 12px;
}

.camera-name {
  margin: 0;
  font-size: 0.86rem;
  font-weight: 600;
}

.recorded-at {
  margin: 2px 0 0;
  font-size: 0.76rem;
  color: var(--p-surface-500);
}
</style>
