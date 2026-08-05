<script setup lang="ts">
import Dialog from "primevue/dialog";
import Message from "primevue/message";
import Skeleton from "primevue/skeleton";
import { computed, ref, watch } from "vue";

import { ApiError, getCameraBatteryEvents } from "@/api";
import BatteryIndicator from "@/components/BatteryIndicator.vue";
import { useFormatting } from "@/composables/useFormatting";
import { BATTERY_STATUS_META, batteryStatus } from "@/lib/battery";

import type { BatteryEventRead, CameraRead } from "@/api";
import type { BatteryStatus } from "@/lib/battery";

const props = defineProps<{ camera: CameraRead | null }>();

const emit = defineEmits<{ close: [] }>();

const { formatDateTime } = useFormatting();

const visible = computed({
  get: () => props.camera !== null,
  set: (value: boolean) => {
    if (!value) {
      emit("close");
    }
  },
});

const events = ref<BatteryEventRead[]>([]);
const loading = ref(false);
const error = ref("");

async function loadEvents(cameraId: string): Promise<void> {
  loading.value = true;
  error.value = "";
  events.value = [];
  try {
    events.value = await getCameraBatteryEvents(cameraId);
  } catch (caught) {
    error.value =
      caught instanceof ApiError ? caught.message : "Could not load battery history.";
  } finally {
    loading.value = false;
  }
}

watch(
  () => props.camera?.id,
  (cameraId) => {
    if (cameraId) {
      void loadEvents(cameraId);
    }
  },
  { immediate: true },
);

interface TimelineSegment {
  status: BatteryStatus;
  label: string;
  occurredAt: string;
  widthPercent: number;
  showLabel: boolean;
}

// A segment's label is only drawn inline when it comfortably fits its own
// width - a narrow sliver relies on its title tooltip and the Activity list
// below instead, rather than clipping or overflowing text (see the dataviz
// skill's "measure first" guidance for inline segment labels).
const MIN_LABEL_PERCENT = 15;

const timeline = computed<TimelineSegment[]>(() => {
  if (events.value.length === 0) {
    return [];
  }
  // events.value comes back newest-first from the API; spans are built
  // oldest-first (each event's state holds until the next event replaces it).
  const oldestFirst = [...events.value].reverse();
  const now = Date.now();
  const spanStartMs = new Date(oldestFirst[0].occurred_at).getTime();
  const totalMs = Math.max(now - spanStartMs, 1);

  return oldestFirst.map((event, index) => {
    const startedAtMs = new Date(event.occurred_at).getTime();
    const nextEvent = oldestFirst[index + 1];
    const endedAtMs = nextEvent ? new Date(nextEvent.occurred_at).getTime() : now;
    const widthPercent = ((endedAtMs - startedAtMs) / totalMs) * 100;
    const status = batteryStatus(event.battery);
    return {
      status,
      // eslint-disable-next-line security/detect-object-injection -- status is the narrow BatteryStatus union, never untrusted input
      label: BATTERY_STATUS_META[status].label,
      occurredAt: event.occurred_at,
      widthPercent,
      showLabel: widthPercent >= MIN_LABEL_PERCENT,
    };
  });
});
</script>

<template>
  <Dialog
    v-model:visible="visible"
    :header="camera?.name ?? 'Battery history'"
    modal
    :style="{ width: '34rem' }"
    :breakpoints="{ '640px': '92vw' }"
    data-testid="battery-history-dialog"
  >
    <div class="current-row">
      <span class="muted">Current status</span>
      <BatteryIndicator :battery="camera?.battery" />
    </div>

    <div
      v-if="loading"
      data-testid="battery-history-loading"
    >
      <Skeleton
        height="60px"
        border-radius="10px"
      />
    </div>

    <Message
      v-else-if="error"
      severity="error"
      :closable="false"
      data-testid="battery-history-error"
    >
      {{ error }}
    </Message>

    <Message
      v-else-if="timeline.length === 0"
      severity="info"
      :closable="false"
      data-testid="battery-history-empty"
    >
      No battery events recorded yet.
    </Message>

    <template v-else>
      <section class="history-section">
        <h4 class="section-title">
          History
        </h4>
        <div
          class="timeline-bar"
          data-testid="battery-timeline"
        >
          <div
            v-for="(segment, index) in timeline"
            :key="index"
            :class="`timeline-segment timeline-segment--${segment.status}`"
            :style="{ width: `${segment.widthPercent}%` }"
            :title="`${segment.label} since ${formatDateTime(segment.occurredAt)}`"
          >
            <span
              v-if="segment.showLabel"
              class="timeline-segment-label"
            >{{ segment.label }}</span>
          </div>
        </div>
        <div class="timeline-ticks">
          <span>{{ formatDateTime(timeline[0].occurredAt) }}</span>
          <span>Now</span>
        </div>
      </section>

      <section class="activity-section">
        <h4 class="section-title">
          Activity
        </h4>
        <ul
          class="activity-list"
          data-testid="battery-activity-list"
        >
          <li
            v-for="event in events"
            :key="event.id"
            class="activity-row"
          >
            <BatteryIndicator :battery="event.battery" />
            <span class="activity-time">{{ formatDateTime(event.occurred_at) }}</span>
          </li>
        </ul>
      </section>
    </template>
  </Dialog>
</template>

<style scoped>
.current-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}

.muted {
  font-size: 0.85rem;
  color: var(--p-surface-500);
}

.section-title {
  margin: 0 0 10px;
  font-size: 0.8rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--p-surface-500);
}

.history-section {
  margin-bottom: 24px;
}

.timeline-bar {
  display: flex;
  gap: 2px;
  height: 28px;
  border-radius: 8px;
  overflow: hidden;
  background: var(--p-surface-100);
}

.blink-dark .timeline-bar {
  background: var(--p-surface-800);
}

.timeline-segment {
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 2px;
}

.timeline-segment--ok {
  background: var(--p-green-500);
}

.timeline-segment--low {
  background: var(--p-red-500);
}

.timeline-segment--unknown {
  background: var(--p-surface-400);
}

.timeline-segment-label {
  font-size: 0.72rem;
  font-weight: 600;
  color: var(--p-surface-0);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  padding: 0 6px;
}

.timeline-ticks {
  display: flex;
  justify-content: space-between;
  margin-top: 6px;
  font-size: 0.72rem;
  color: var(--p-surface-500);
}

.activity-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 220px;
  overflow-y: auto;
}

.activity-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 6px 0;
  border-bottom: 1px solid var(--p-surface-100);
}

.blink-dark .activity-row {
  border-bottom-color: var(--p-surface-800);
}

.activity-row:last-child {
  border-bottom: none;
}

.activity-time {
  font-size: 0.82rem;
  color: var(--p-surface-500);
}
</style>
