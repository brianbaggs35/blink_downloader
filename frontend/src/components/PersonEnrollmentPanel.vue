<script setup lang="ts">
import Button from "primevue/button";
import Message from "primevue/message";
import Select from "primevue/select";
import SelectButton from "primevue/selectbutton";
import Skeleton from "primevue/skeleton";
import { ref, watch } from "vue";

import { ApiError, clipThumbnailUrl, enrollFace, listCameras, listClips } from "@/api";
import ClipFramePicker from "@/components/ClipFramePicker.vue";
import { useFormatting } from "@/composables/useFormatting";

import type { CameraRead, ClipRead, DetectedFaceRead } from "@/api";

const props = defineProps<{
  personId: string;
}>();

const emit = defineEmits<{
  enrolled: [];
}>();

const { formatDateTime, formatDuration } = useFormatting();

// Capped at 7 days: "30 days" or "All time" on an active household camera
// can turn up hundreds to thousands of clips, which is a client-side list
// nobody can usefully scroll through anyway - see PersonEnrollmentPanel's
// clip-list scroll container below.
const TIME_RANGE_OPTIONS: { label: string; hours: number }[] = [
  { label: "24 hours", hours: 24 },
  { label: "48 hours", hours: 48 },
  { label: "7 days", hours: 24 * 7 },
];

const cameras = ref<CameraRead[]>([]);
const camerasError = ref("");
const cameraId = ref<string | null>(null);
const timeRange = ref(TIME_RANGE_OPTIONS[0]!);

const clips = ref<ClipRead[]>([]);
const clipsLoading = ref(false);
const clipsError = ref("");
const selectedClip = ref<ClipRead | null>(null);

const currentSelection = ref<{ frameSeconds: number; face: DetectedFaceRead } | null>(null);

const enrolling = ref(false);
const enrollError = ref("");
const justEnrolled = ref(false);

async function loadCameras(): Promise<void> {
  camerasError.value = "";
  try {
    cameras.value = await listCameras();
  } catch (caught) {
    camerasError.value = caught instanceof ApiError ? caught.message : "Could not load cameras.";
  }
}

void loadCameras();

async function loadClips(): Promise<void> {
  selectedClip.value = null;
  currentSelection.value = null;
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

function selectClip(clip: ClipRead): void {
  selectedClip.value = clip;
  currentSelection.value = null;
  justEnrolled.value = false;
}

async function confirmEnroll(): Promise<void> {
  // Only reachable via the button, which is disabled unless both are set.
  const clip = selectedClip.value!;
  const selection = currentSelection.value!;
  enrolling.value = true;
  enrollError.value = "";
  try {
    await enrollFace(props.personId, {
      clip_id: clip.id,
      frame_seconds: selection.frameSeconds,
      bbox: selection.face.bbox,
    });
    justEnrolled.value = true;
    currentSelection.value = null;
    emit("enrolled");
  } catch (caught) {
    enrollError.value = caught instanceof ApiError ? caught.message : "Could not enroll this face.";
  } finally {
    enrolling.value = false;
  }
}
</script>

<template>
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
        <label
          for="enroll-camera-select"
          class="sr-only"
        >Camera</label>
        <Select
          v-model="cameraId"
          input-id="enroll-camera-select"
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
      <ClipFramePicker
        :key="selectedClip.id"
        :clip-id="selectedClip.id"
        :duration-seconds="selectedClip.duration_seconds"
        @selection-change="currentSelection = $event"
      />
    </section>

    <Message
      v-if="justEnrolled"
      severity="success"
      :closable="false"
      data-testid="enroll-success"
    >
      Face enrolled. Pick another frame (or clip) to add more.
    </Message>
    <Message
      v-if="enrollError"
      severity="error"
      :closable="false"
      data-testid="enroll-error"
    >
      {{ enrollError }}
    </Message>

    <div
      v-if="selectedClip"
      class="confirm-row"
    >
      <Button
        label="Enroll this face"
        :disabled="currentSelection === null"
        :loading="enrolling"
        data-testid="enroll-confirm"
        @click="confirmEnroll"
      />
    </div>
  </div>
</template>

<style scoped>
.wizard {
  display: flex;
  flex-direction: column;
  gap: 22px;
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
  border: 1px solid var(--p-surface-200);
  border-radius: 10px;
  padding: 8px;
  padding-right: 4px;
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

.confirm-row {
  display: flex;
  justify-content: flex-end;
}
</style>
