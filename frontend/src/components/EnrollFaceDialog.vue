<script setup lang="ts">
import Button from "primevue/button";
import Dialog from "primevue/dialog";
import Message from "primevue/message";
import Select from "primevue/select";
import SelectButton from "primevue/selectbutton";
import Skeleton from "primevue/skeleton";
import Slider from "primevue/slider";
import { computed, ref, watch } from "vue";

import {
  ApiError,
  clipFrameUrl,
  clipThumbnailUrl,
  detectFacesInClipFrame,
  enrollFace,
  listCameras,
  listClips,
} from "@/api";
import { useFormatting } from "@/composables/useFormatting";

import type { CameraRead, ClipRead, DetectedFaceRead } from "@/api";

const props = defineProps<{
  personId: string | null;
  personName: string;
}>();

const emit = defineEmits<{
  close: [];
  enrolled: [];
}>();

const { formatDateTime, formatDuration } = useFormatting();

const visible = computed({
  get: () => props.personId !== null,
  set: (value: boolean) => {
    if (!value) {
      emit("close");
    }
  },
});

const TIME_RANGE_OPTIONS: { label: string; hours: number | null }[] = [
  { label: "24 hours", hours: 24 },
  { label: "48 hours", hours: 48 },
  { label: "7 days", hours: 24 * 7 },
  { label: "30 days", hours: 24 * 30 },
  { label: "All time", hours: null },
];

const cameras = ref<CameraRead[]>([]);
const camerasError = ref("");
const cameraId = ref<string | null>(null);
const timeRange = ref(TIME_RANGE_OPTIONS[0]!);

const clips = ref<ClipRead[]>([]);
const clipsLoading = ref(false);
const clipsError = ref("");
const selectedClip = ref<ClipRead | null>(null);

const frameSeconds = ref(0);
const detectedFaces = ref<DetectedFaceRead[]>([]);
const detecting = ref(false);
const frameError = ref("");
const selectedFaceIndex = ref<number | null>(null);

const enrolling = ref(false);
const enrollError = ref("");

function resetForNewSession(): void {
  cameraId.value = null;
  timeRange.value = TIME_RANGE_OPTIONS[0]!;
  clips.value = [];
  clipsError.value = "";
  selectedClip.value = null;
  detectedFaces.value = [];
  selectedFaceIndex.value = null;
  frameError.value = "";
  enrollError.value = "";
}

watch(
  () => props.personId,
  (personId) => {
    if (personId === null) {
      return;
    }
    resetForNewSession();
    if (cameras.value.length === 0) {
      void loadCameras();
    }
  },
  { immediate: true },
);

async function loadCameras(): Promise<void> {
  camerasError.value = "";
  try {
    cameras.value = await listCameras();
  } catch (caught) {
    camerasError.value = caught instanceof ApiError ? caught.message : "Could not load cameras.";
  }
}

async function loadClips(): Promise<void> {
  selectedClip.value = null;
  detectedFaces.value = [];
  selectedFaceIndex.value = null;
  if (!cameraId.value) {
    clips.value = [];
    return;
  }
  clipsLoading.value = true;
  clipsError.value = "";
  try {
    const since =
      timeRange.value.hours === null
        ? undefined
        : new Date(Date.now() - timeRange.value.hours * 60 * 60 * 1000).toISOString();
    const response = await listClips({
      camera_id: cameraId.value,
      since,
      downloaded_only: true,
      page_size: 50,
    });
    clips.value = response.items;
  } catch (caught) {
    clipsError.value = caught instanceof ApiError ? caught.message : "Could not load clips.";
  } finally {
    clipsLoading.value = false;
  }
}

watch([cameraId, timeRange], () => void loadClips());

async function refreshFrame(): Promise<void> {
  // Only reachable via selectClip() (which just set selectedClip) or the
  // scrubber's change handler (rendered only inside the template's
  // v-if="selectedClip" block) - selectedClip is never null here.
  const clip = selectedClip.value!;
  detecting.value = true;
  frameError.value = "";
  selectedFaceIndex.value = null;
  try {
    detectedFaces.value = await detectFacesInClipFrame(clip.id, frameSeconds.value);
  } catch (caught) {
    detectedFaces.value = [];
    frameError.value =
      caught instanceof ApiError ? caught.message : "Could not detect faces in this frame.";
  } finally {
    detecting.value = false;
  }
}

function selectClip(clip: ClipRead): void {
  selectedClip.value = clip;
  frameSeconds.value = Math.round((clip.duration_seconds ?? 10) / 2);
  void refreshFrame();
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

async function confirmEnroll(): Promise<void> {
  // Only reachable via the button, which is disabled unless both are set.
  const clip = selectedClip.value!;
  const face = detectedFaces.value[selectedFaceIndex.value!]!;
  enrolling.value = true;
  enrollError.value = "";
  try {
    await enrollFace(props.personId!, {
      clip_id: clip.id,
      frame_seconds: frameSeconds.value,
      bbox: face.bbox,
    });
    emit("enrolled");
    visible.value = false;
  } catch (caught) {
    enrollError.value = caught instanceof ApiError ? caught.message : "Could not enroll this face.";
  } finally {
    enrolling.value = false;
  }
}
</script>

<template>
  <Dialog
    v-model:visible="visible"
    modal
    :header="`Enroll a face for ${personName}`"
    :style="{ width: '68rem', maxWidth: '96vw' }"
    :breakpoints="{ '768px': '96vw' }"
    data-testid="enroll-dialog"
  >
    <div class="wizard">
      <section class="step">
        <h4 class="step-title">
          1. Camera and time range
        </h4>
        <Message
          v-if="camerasError"
          severity="error"
          :closable="false"
        >
          {{ camerasError }}
        </Message>
        <div class="step-controls">
          <Select
            v-model="cameraId"
            :options="cameras"
            option-label="name"
            option-value="id"
            placeholder="Choose a camera"
            data-testid="enroll-camera-select"
          />
          <SelectButton
            v-model="timeRange"
            :options="TIME_RANGE_OPTIONS"
            option-label="label"
            :allow-empty="false"
            data-testid="enroll-time-range"
          />
        </div>
      </section>

      <section
        v-if="cameraId"
        class="step"
      >
        <h4 class="step-title">
          2. Pick a clip
        </h4>
        <div
          v-if="clipsLoading"
          data-testid="enroll-clips-loading"
        >
          <Skeleton
            height="64px"
            border-radius="8px"
          />
        </div>
        <Message
          v-else-if="clipsError"
          severity="error"
          :closable="false"
        >
          {{ clipsError }}
        </Message>
        <p
          v-else-if="clips.length === 0"
          class="muted"
        >
          No downloaded clips from this camera in the selected time range.
        </p>
        <div
          v-else
          class="clip-list"
          data-testid="enroll-clip-list"
        >
          <button
            v-for="clip in clips"
            :key="clip.id"
            type="button"
            class="clip-item"
            :class="{ active: selectedClip?.id === clip.id }"
            :data-testid="`enroll-clip-${clip.id}`"
            @click="selectClip(clip)"
          >
            <img
              v-if="clip.thumbnail_generated"
              :src="clipThumbnailUrl(clip.id)"
              alt=""
              class="clip-thumb"
            >
            <div
              v-else
              class="clip-thumb clip-thumb-fallback"
            >
              <i
                class="pi pi-video"
                aria-hidden="true"
              />
            </div>
            <span class="clip-time">{{ formatDateTime(clip.recorded_at) }}</span>
            <span class="clip-duration muted">{{ formatDuration(clip.duration_seconds) }}</span>
          </button>
        </div>
      </section>

      <section
        v-if="selectedClip"
        class="step"
      >
        <h4 class="step-title">
          3. Find the face
        </h4>
        <div class="frame-container">
          <img
            :src="clipFrameUrl(selectedClip.id, frameSeconds)"
            alt="Selected clip frame"
            class="frame-image"
            data-testid="enroll-frame-image"
          >
          <div class="face-overlay">
            <button
              v-for="(face, index) in detectedFaces"
              :key="index"
              type="button"
              class="face-box"
              :class="{ selected: selectedFaceIndex === index }"
              :style="faceBoxStyle(face)"
              :data-testid="`enroll-face-box-${index}`"
              :aria-label="`Detected face ${index + 1}, confidence ${Math.round(face.confidence * 100)}%`"
              @click="selectedFaceIndex = index"
            />
          </div>
        </div>

        <div class="scrubber">
          <Slider
            v-model="frameSeconds"
            :min="0"
            :max="Math.max(selectedClip.duration_seconds ?? 10, 1)"
            :step="0.5"
            data-testid="enroll-scrubber"
            @change="refreshFrame"
          />
          <span class="muted">{{ frameSeconds.toFixed(1) }}s / {{ formatDuration(selectedClip.duration_seconds) }}</span>
        </div>

        <p
          v-if="detecting"
          class="muted"
          data-testid="enroll-detecting"
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
          data-testid="enroll-no-faces"
        >
          No faces detected in this frame. Try scrubbing to a moment where the person is clearly
          visible.
        </p>
        <p
          v-else
          class="muted"
        >
          {{ detectedFaces.length }} face(s) found — click one to select it for enrollment.
        </p>
      </section>

      <Message
        v-if="enrollError"
        severity="error"
        :closable="false"
        data-testid="enroll-error"
      >
        {{ enrollError }}
      </Message>
    </div>

    <template #footer>
      <Button
        label="Cancel"
        severity="secondary"
        text
        @click="visible = false"
      />
      <Button
        label="Enroll this face"
        :disabled="selectedFaceIndex === null"
        :loading="enrolling"
        data-testid="enroll-confirm"
        @click="confirmEnroll"
      />
    </template>
  </Dialog>
</template>

<style scoped>
.wizard {
  display: flex;
  flex-direction: column;
  gap: 22px;
  max-height: 70vh;
  overflow-y: auto;
  padding-right: 4px;
}

.step {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.step-title {
  margin: 0;
  font-size: 0.85rem;
  font-weight: 700;
}

.step-controls {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
}

.muted {
  margin: 0;
  font-size: 0.82rem;
  color: var(--p-surface-500);
}

.clip-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 240px;
  overflow-y: auto;
  padding-right: 4px;
  border: 1px solid var(--p-surface-200);
  border-radius: 10px;
  padding: 8px;
}

.blink-dark .clip-list {
  border-color: var(--p-surface-800);
}

.clip-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 8px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: none;
  cursor: pointer;
  text-align: left;
  font: inherit;
  color: inherit;
}

.clip-item:hover {
  background: var(--p-surface-100);
}

.blink-dark .clip-item:hover {
  background: color-mix(in srgb, var(--p-surface-800) 60%, transparent);
}

.clip-item.active {
  border-color: var(--p-primary-400);
  background: color-mix(in srgb, var(--p-primary-500) 12%, transparent);
}

.clip-thumb {
  width: 72px;
  height: 40px;
  border-radius: 6px;
  object-fit: cover;
  flex-shrink: 0;
}

.clip-thumb-fallback {
  display: grid;
  place-items: center;
  background: var(--p-surface-100);
}

.blink-dark .clip-thumb-fallback {
  background: var(--p-surface-800);
}

.clip-time {
  font-size: 0.82rem;
  font-weight: 600;
}

.clip-duration {
  margin-left: auto;
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
