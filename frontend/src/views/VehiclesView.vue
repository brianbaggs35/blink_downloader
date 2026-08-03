<script setup lang="ts">
import Button from "primevue/button";
import Message from "primevue/message";
import Skeleton from "primevue/skeleton";
import Tag from "primevue/tag";
import { onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";

import { ApiError, listProximityEvents, listVehicles, vehicleReferenceFrameUrl } from "@/api";
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
import { useFormatting } from "@/composables/useFormatting";
import { useAuthStore } from "@/stores/auth";

import type { ProximityEventRead, VehicleRead } from "@/api";

const RECENT_EVENTS_LIMIT = 5;

const router = useRouter();
const auth = useAuthStore();
const { formatDateTime } = useFormatting();

const vehicles = ref<VehicleRead[]>([]);
const loading = ref(true);
const loadError = ref("");

const eventsByCamera = reactive<Record<string, ProximityEventRead[]>>({});
const eventsLoading = reactive<Record<string, boolean>>({});
const eventsError = reactive<Record<string, string>>({});

function polygonAttr(points: number[][]): string {
  return points.map(([x, y]) => `${x! * 100},${y! * 100}`).join(" ");
}

async function loadEventsFor(vehicle: VehicleRead): Promise<void> {
  eventsLoading[vehicle.camera_id] = true;
  eventsError[vehicle.camera_id] = "";
  try {
    const events = await listProximityEvents(vehicle.camera_id);
    eventsByCamera[vehicle.camera_id] = events.slice(0, RECENT_EVENTS_LIMIT);
  } catch (caught) {
    eventsError[vehicle.camera_id] =
      caught instanceof ApiError ? caught.message : "Could not load recent activity.";
  } finally {
    eventsLoading[vehicle.camera_id] = false;
  }
}

async function load(): Promise<void> {
  loading.value = true;
  loadError.value = "";
  try {
    vehicles.value = await listVehicles();
    void Promise.all(vehicles.value.map((vehicle) => loadEventsFor(vehicle)));
  } catch (caught) {
    loadError.value = caught instanceof ApiError ? caught.message : "Could not load vehicles.";
  } finally {
    loading.value = false;
  }
}

onMounted(load);

function viewClips(cameraId: string): void {
  router.push({ name: "library", query: { camera_id: cameraId } });
}
</script>

<template>
  <section>
    <PageHeader
      title="Vehicles"
      description="Vehicles the system is watching, and recent proximity activity."
    >
      <template #actions>
        <Button
          v-if="auth.isAdmin"
          label="Manage vehicles"
          icon="pi pi-cog"
          severity="secondary"
          outlined
          data-testid="go-vehicle-settings"
          @click="router.push({ name: 'settings', query: { tab: 'vehicles' } })"
        />
      </template>
    </PageHeader>

    <div
      v-if="loading"
      class="cards"
      data-testid="vehicles-loading"
    >
      <Skeleton
        height="220px"
        border-radius="14px"
      />
    </div>

    <EmptyState
      v-else-if="loadError"
      icon="pi pi-exclamation-triangle"
      title="Couldn't load vehicles"
      description="We weren't able to reach the server. Check your connection and try again."
      data-testid="vehicles-load-error"
    >
      <template #actions>
        <Button
          label="Retry"
          icon="pi pi-refresh"
          severity="secondary"
          outlined
          data-testid="retry-vehicles"
          @click="load"
        />
      </template>
    </EmptyState>

    <EmptyState
      v-else-if="vehicles.length === 0"
      icon="pi pi-car"
      title="No vehicles protected yet"
      description="Draw an outline around a vehicle in a camera's view, and this page will track how close people get to it."
      data-testid="vehicles-empty"
    >
      <template #actions>
        <Button
          v-if="auth.isAdmin"
          label="Set up a vehicle"
          icon="pi pi-cog"
          data-testid="go-vehicle-settings-empty"
          @click="router.push({ name: 'settings', query: { tab: 'vehicles' } })"
        />
      </template>
    </EmptyState>

    <div
      v-else
      class="cards"
    >
      <article
        v-for="vehicle in vehicles"
        :key="vehicle.id"
        class="vehicle-card"
        :data-testid="`vehicle-card-${vehicle.camera_id}`"
      >
        <div class="card-header">
          <div>
            <span class="camera-name">{{ vehicle.camera_name }}</span>
            <span class="description">{{ vehicle.description }}</span>
          </div>
          <Tag
            :value="vehicle.enabled ? 'Active' : 'Paused'"
            :severity="vehicle.enabled ? 'success' : 'secondary'"
          />
        </div>

        <div
          v-if="vehicle.has_reference_frame"
          class="frame-container"
        >
          <img
            :src="vehicleReferenceFrameUrl(vehicle.camera_id)"
            alt="Camera reference frame with the protected vehicle outlined"
            class="frame-image"
          >
          <svg
            class="outline-svg"
            viewBox="0 0 100 100"
            preserveAspectRatio="none"
          >
            <polygon
              :points="polygonAttr(vehicle.outline_points)"
              class="outline-polygon"
            />
          </svg>
        </div>

        <dl class="stats">
          <div class="stat">
            <dt>Length</dt>
            <dd>{{ vehicle.estimated_length_feet }} ft</dd>
          </div>
          <div class="stat">
            <dt>Alerts within</dt>
            <dd>{{ vehicle.distance_threshold_feet }} ft</dd>
          </div>
        </dl>

        <div class="events">
          <div class="events-header">
            <h4>Recent proximity events</h4>
            <Button
              label="View clips from this camera"
              icon="pi pi-images"
              text
              size="small"
              :data-testid="`view-clips-${vehicle.camera_id}`"
              @click="viewClips(vehicle.camera_id)"
            />
          </div>

          <Skeleton
            v-if="eventsLoading[vehicle.camera_id]"
            height="20px"
            :data-testid="`events-loading-${vehicle.camera_id}`"
          />
          <Message
            v-else-if="eventsError[vehicle.camera_id]"
            severity="error"
            :closable="false"
            :data-testid="`events-error-${vehicle.camera_id}`"
          >
            {{ eventsError[vehicle.camera_id] }}
          </Message>
          <p
            v-else-if="eventsByCamera[vehicle.camera_id]!.length === 0"
            class="muted"
            :data-testid="`events-empty-${vehicle.camera_id}`"
          >
            No proximity breaches recorded yet.
          </p>
          <ul
            v-else
            class="event-list"
            :data-testid="`event-list-${vehicle.camera_id}`"
          >
            <li
              v-for="event in eventsByCamera[vehicle.camera_id]"
              :key="event.id"
            >
              <span class="event-distance">
                {{ event.distance_feet.toFixed(1) }} ft (±{{ event.error_margin_feet.toFixed(1) }} ft)
              </span>
              <span class="event-time">{{ formatDateTime(event.occurred_at) }}</span>
            </li>
          </ul>
        </div>
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

.vehicle-card {
  padding: 20px 22px;
  border-radius: 14px;
  border: 1px solid var(--p-surface-200);
  background: var(--p-surface-0);
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.blink-dark .vehicle-card {
  border-color: var(--p-surface-800);
  background: color-mix(in srgb, var(--p-surface-900) 60%, transparent);
}

.card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.camera-name {
  display: block;
  font-size: 0.95rem;
  font-weight: 700;
}

.description {
  display: block;
  font-size: 0.82rem;
  color: var(--p-surface-500);
  margin-top: 2px;
}

.frame-container {
  position: relative;
  max-width: 420px;
  border-radius: 8px;
  overflow: hidden;
  line-height: 0;
}

.frame-image {
  width: 100%;
  height: auto;
  display: block;
}

.outline-svg {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}

.outline-polygon {
  fill: color-mix(in srgb, var(--p-primary-500) 20%, transparent);
  stroke: var(--p-primary-400);
  stroke-width: 0.5;
}

.stats {
  display: flex;
  gap: 28px;
  margin: 0;
}

.stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.stat dt {
  font-size: 0.75rem;
  color: var(--p-surface-500);
}

.stat dd {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 600;
}

.events {
  padding-top: 12px;
  border-top: 1px solid var(--p-surface-200);
}

.blink-dark .events {
  border-color: var(--p-surface-800);
}

.events-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.events-header h4 {
  margin: 0;
  font-size: 0.8rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  color: var(--p-surface-500);
}

.muted {
  margin: 0;
  font-size: 0.82rem;
  color: var(--p-surface-500);
}

.event-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.event-list li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-size: 0.82rem;
}

.event-distance {
  font-weight: 600;
}

.event-time {
  color: var(--p-surface-500);
}
</style>
