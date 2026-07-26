<script setup lang="ts">
import Message from "primevue/message";
import Slider from "primevue/slider";
import { ref, watch } from "vue";

import { ApiError, clipFrameUrl, detectFacesInClipFrame } from "@/api";
import { useFormatting } from "@/composables/useFormatting";

import type { DetectedFaceRead } from "@/api";

const props = defineProps<{
  clipId: string;
  durationSeconds: number | null;
}>();

const emit = defineEmits<{
  "selection-change": [selection: { frameSeconds: number; face: DetectedFaceRead } | null];
}>();

const { formatDuration } = useFormatting();

const frameSeconds = ref(0);
const detectedFaces = ref<DetectedFaceRead[]>([]);
const detecting = ref(false);
const frameError = ref("");
const selectedFaceIndex = ref<number | null>(null);

function emitSelection(): void {
  const face = selectedFaceIndex.value === null ? null : detectedFaces.value[selectedFaceIndex.value];
  emit("selection-change", face ? { frameSeconds: frameSeconds.value, face } : null);
}

async function refreshFrame(): Promise<void> {
  detecting.value = true;
  frameError.value = "";
  selectedFaceIndex.value = null;
  emitSelection();
  try {
    detectedFaces.value = await detectFacesInClipFrame(props.clipId, frameSeconds.value);
  } catch (caught) {
    detectedFaces.value = [];
    frameError.value =
      caught instanceof ApiError ? caught.message : "Could not detect faces in this frame.";
  } finally {
    detecting.value = false;
  }
}

watch(
  () => props.clipId,
  () => {
    frameSeconds.value = Math.round((props.durationSeconds ?? 10) / 2);
    void refreshFrame();
  },
  { immediate: true },
);

function selectFace(index: number): void {
  selectedFaceIndex.value = index;
  emitSelection();
}

function faceBoxStyle(face: DetectedFaceRead): Record<string, string> {
  const [x, y, w, h] = face.bbox;
  return {
    left: `${x * 100}%`,
    top: `${y * 100}%`,
    width: `${w * 100}%`,
    height: `${h * 100}%`,
  };
}
</script>

<template>
  <div class="picker">
    <div class="frame-container">
      <img
        :src="clipFrameUrl(clipId, frameSeconds)"
        alt="Selected clip frame"
        class="frame-image"
        data-testid="picker-frame-image"
      >
      <div class="face-overlay">
        <button
          v-for="(face, index) in detectedFaces"
          :key="index"
          type="button"
          class="face-box"
          :class="{ selected: selectedFaceIndex === index }"
          :style="faceBoxStyle(face)"
          :data-testid="`picker-face-box-${index}`"
          :aria-label="`Detected face ${index + 1}, confidence ${Math.round(face.confidence * 100)}%`"
          @click="selectFace(index)"
        />
      </div>
    </div>

    <div class="scrubber">
      <Slider
        v-model="frameSeconds"
        :min="0"
        :max="Math.max(durationSeconds ?? 10, 1)"
        :step="0.5"
        data-testid="picker-scrubber"
        @change="refreshFrame"
      />
      <span class="muted">{{ frameSeconds.toFixed(1) }}s / {{ formatDuration(durationSeconds) }}</span>
    </div>

    <p
      v-if="detecting"
      class="muted"
      data-testid="picker-detecting"
    >
      Detecting faces…
    </p>
    <Message
      v-else-if="frameError"
      severity="error"
      :closable="false"
    >
      {{ frameError }}
    </Message>
    <p
      v-else-if="detectedFaces.length === 0"
      class="muted"
      data-testid="picker-no-faces"
    >
      No faces detected in this frame. Try scrubbing to a moment where the person is clearly
      visible.
    </p>
    <p
      v-else
      class="muted"
    >
      {{ detectedFaces.length }} face(s) found — click one to select it.
    </p>
  </div>
</template>

<style scoped>
.picker {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.muted {
  margin: 0;
  font-size: 0.82rem;
  color: var(--p-surface-500);
}

.frame-container {
  position: relative;
  width: 100%;
  max-width: 560px;
  border-radius: 10px;
  overflow: hidden;
  line-height: 0;
  background: var(--p-surface-100);
}

.blink-dark .frame-container {
  background: var(--p-surface-800);
}

.frame-image {
  width: 100%;
  height: auto;
  display: block;
}

.face-overlay {
  position: absolute;
  inset: 0;
}

.face-box {
  position: absolute;
  border: 2px solid var(--p-primary-400);
  background: color-mix(in srgb, var(--p-primary-500) 15%, transparent);
  border-radius: 4px;
  cursor: pointer;
  padding: 0;
}

.face-box.selected {
  border-color: var(--p-green-500);
  background: color-mix(in srgb, var(--p-green-500) 25%, transparent);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--p-green-500) 40%, transparent);
}

.scrubber {
  display: flex;
  align-items: center;
  gap: 14px;
  max-width: 560px;
}

.scrubber :deep(.p-slider) {
  flex: 1;
}
</style>
