<script setup lang="ts">
import Button from "primevue/button";
import InputNumber from "primevue/inputnumber";
import InputText from "primevue/inputtext";
import Message from "primevue/message";
import Skeleton from "primevue/skeleton";
import ToggleSwitch from "primevue/toggleswitch";
import { useToast } from "primevue/usetoast";
import { onMounted, reactive, ref } from "vue";

import {
  ApiError,
  captureVehicleReferenceFrame,
  deleteVehicle,
  getVehicle,
  listCameras,
  putVehicle,
  vehicleReferenceFrameUrl,
} from "@/api";
import { useDeleteConfirm } from "@/composables/useDeleteConfirm";

import type { CameraRead } from "@/api";

const MIN_OUTLINE_POINTS = 3;
// Matches VehicleUpdate.outline_points' backend cap (200) with headroom -
// a real car-sized freeform stroke never gets remotely close to this; it
// only guards against someone dragging back and forth for a long time.
const MAX_OUTLINE_POINTS = 150;
// Unit-space (0-1) minimum gap between consecutively captured points while
// drawing - without this, a real pointer's move-event rate would append a
// point on nearly every animation frame, ballooning the saved outline to
// hundreds of points for a shape that only needs a few dozen at most.
const DRAW_MIN_POINT_DISTANCE = 0.015;
const DEFAULT_LENGTH_FEET = 15;
const DEFAULT_THRESHOLD_FEET = 6;

interface Point {
  x: number;
  y: number;
}

interface VehicleFormState {
  loading: boolean;
  saving: boolean;
  capturing: boolean;
  deleting: boolean;
  error: string;
  vehicleId: string | null;
  hasReferenceFrame: boolean;
  frameNonce: number;
  points: Point[];
  description: string;
  estimatedLengthFeet: number;
  distanceThresholdFeet: number;
  enabled: boolean;
}

function emptyState(): VehicleFormState {
  return {
    loading: true,
    saving: false,
    capturing: false,
    deleting: false,
    error: "",
    vehicleId: null,
    hasReferenceFrame: false,
    frameNonce: 0,
    points: [],
    description: "",
    estimatedLengthFeet: DEFAULT_LENGTH_FEET,
    distanceThresholdFeet: DEFAULT_THRESHOLD_FEET,
    enabled: true,
  };
}

const toast = useToast();
const { confirmDelete } = useDeleteConfirm();

const cameras = ref<CameraRead[]>([]);
const camerasLoading = ref(true);
const camerasError = ref("");
const forms = reactive<Record<string, VehicleFormState>>({});

async function loadVehicleFor(camera: CameraRead): Promise<void> {
  // loadAll() seeds forms for every camera before this can be called.
  const form = forms[camera.id];
  try {
    const vehicle = await getVehicle(camera.id);
    form.vehicleId = vehicle.id;
    form.hasReferenceFrame = vehicle.has_reference_frame;
    form.points = vehicle.outline_points.map(([x, y]) => ({ x, y }));
    form.description = vehicle.description;
    form.estimatedLengthFeet = vehicle.estimated_length_feet;
    form.distanceThresholdFeet = vehicle.distance_threshold_feet;
    form.enabled = vehicle.enabled;
  } catch (caught) {
    if (!(caught instanceof ApiError) || caught.status !== 404) {
      form.error = caught instanceof ApiError ? caught.message : "Could not load this camera's vehicle setup.";
    }
  } finally {
    form.loading = false;
  }
}

async function loadAll(): Promise<void> {
  camerasLoading.value = true;
  camerasError.value = "";
  try {
    cameras.value = await listCameras();
    for (const camera of cameras.value) {
      forms[camera.id] = emptyState();
    }
    // Each camera's vehicle setup loads independently so one slow lookup
    // doesn't block the rest of the list from rendering.
    void Promise.all(cameras.value.map((camera) => loadVehicleFor(camera)));
  } catch (caught) {
    camerasError.value = caught instanceof ApiError ? caught.message : "Could not load cameras.";
  } finally {
    camerasLoading.value = false;
  }
}

onMounted(loadAll);

async function captureFrame(camera: CameraRead): Promise<void> {
  const form = forms[camera.id];
  form.error = "";
  form.capturing = true;
  try {
    await captureVehicleReferenceFrame(camera.id);
    form.hasReferenceFrame = true;
    form.frameNonce += 1;
  } catch (caught) {
    form.error =
      caught instanceof ApiError
        ? caught.message
        : "Could not capture a reference frame. Make sure this camera has at least one downloaded clip.";
  } finally {
    form.capturing = false;
  }
}

function clampUnit(value: number): number {
  return Math.min(1, Math.max(0, value));
}

/** null when the svg hasn't been laid out yet (zero size). */
function unitPointFromEvent(svg: SVGSVGElement, event: MouseEvent): Point | null {
  const rect = svg.getBoundingClientRect();
  if (rect.width === 0 || rect.height === 0) {
    return null;
  }
  return {
    x: clampUnit((event.clientX - rect.left) / rect.width),
    y: clampUnit((event.clientY - rect.top) / rect.height),
  };
}

// A freeform draw is only ever active for one camera's outline at a time -
// tracked here rather than per-form since it's transient UI state, not
// something worth persisting or reacting to elsewhere. Starting a new
// stroke always replaces whatever outline already existed, the same way a
// lasso tool's next drag replaces its previous selection rather than
// trying to merge two disconnected shapes into one.
let drawingCameraId: string | null = null;

function startDrawing(cameraId: string, event: PointerEvent): void {
  event.preventDefault();
  const point = unitPointFromEvent(event.currentTarget as SVGSVGElement, event);
  if (!point) {
    return;
  }
  // Keeps receiving pointermove/pointerup for this gesture even if the
  // cursor briefly leaves the SVG's bounds mid-drag (a fast real drag can
  // easily outrun a small preview image).
  (event.currentTarget as SVGSVGElement).setPointerCapture(event.pointerId);
  drawingCameraId = cameraId;
  // cameraId always comes from our own camera list, never external input.
  // eslint-disable-next-line security/detect-object-injection
  forms[cameraId].points = [point];
}

function continueDrawing(cameraId: string, event: PointerEvent): void {
  if (drawingCameraId !== cameraId) {
    return;
  }
  // cameraId always comes from our own camera list, never external input.
  // eslint-disable-next-line security/detect-object-injection
  const form = forms[cameraId];
  if (form.points.length >= MAX_OUTLINE_POINTS) {
    return;
  }
  const point = unitPointFromEvent(event.currentTarget as SVGSVGElement, event);
  if (!point) {
    return;
  }
  const last = form.points.at(-1);
  if (last && Math.hypot(point.x - last.x, point.y - last.y) < DRAW_MIN_POINT_DISTANCE) {
    return;
  }
  form.points = [...form.points, point];
}

function stopDrawing(cameraId: string): void {
  if (drawingCameraId !== cameraId) {
    return;
  }
  drawingCameraId = null;
}

function outlineHint(form: VehicleFormState): string {
  return form.points.length >= MIN_OUTLINE_POINTS
    ? "Outline drawn. Not quite right? Just draw over it again, or Clear and start over."
    : "Press and drag around the vehicle to draw its outline - like a paintbrush.";
}

function clearPoints(cameraId: string): void {
  // cameraId always comes from our own camera list, never external input.
  // eslint-disable-next-line security/detect-object-injection
  const form = forms[cameraId];
  form.points = [];
}

function polygonAttr(points: Point[]): string {
  return points.map((p) => `${p.x * 100},${p.y * 100}`).join(" ");
}

function canSave(form: VehicleFormState): boolean {
  return form.points.length >= MIN_OUTLINE_POINTS && form.description.trim().length > 0;
}

async function saveVehicle(camera: CameraRead): Promise<void> {
  // Only reachable via the Save button, which is disabled unless canSave().
  const form = forms[camera.id];
  form.error = "";
  form.saving = true;
  try {
    const vehicle = await putVehicle(camera.id, {
      description: form.description.trim(),
      outline_points: form.points.map((p): [number, number] => [p.x, p.y]),
      estimated_length_feet: form.estimatedLengthFeet,
      distance_threshold_feet: form.distanceThresholdFeet,
      enabled: form.enabled,
    });
    form.vehicleId = vehicle.id;
    form.enabled = vehicle.enabled;
    toast.add({ severity: "success", summary: `Saved vehicle protection for ${camera.name}`, life: 2500 });
  } catch (caught) {
    form.error = caught instanceof ApiError ? caught.message : "Unexpected error.";
  } finally {
    form.saving = false;
  }
}

function confirmRemoveVehicle(camera: CameraRead): void {
  confirmDelete({
    header: "Remove vehicle protection",
    message: `Stop protecting a vehicle on ${camera.name}? This removes the saved outline and thresholds.`,
    acceptLabel: "Remove",
    onAccept: () => void performDelete(camera),
  });
}

async function performDelete(camera: CameraRead): Promise<void> {
  const form = forms[camera.id];
  form.deleting = true;
  try {
    await deleteVehicle(camera.id);
    forms[camera.id] = emptyState();
    forms[camera.id].loading = false;
    forms[camera.id].hasReferenceFrame = form.hasReferenceFrame;
    toast.add({ severity: "success", summary: "Vehicle protection removed", life: 2500 });
  } catch (caught) {
    toast.add({
      severity: "error",
      summary: "Could not remove vehicle protection",
      detail: caught instanceof ApiError ? caught.message : "Unexpected error.",
      life: 4000,
    });
  } finally {
    form.deleting = false;
  }
}
</script>

<template>
  <article class="panel">
    <h3 class="panel-title">
      Vehicles
    </h3>
    <p class="panel-hint">
      Draw an outline around a vehicle in each camera's view, and we'll estimate how close people
      get to it using the outline's real-world length as a reference — no depth sensor needed.
      Works best on a camera that doesn't move.
    </p>

    <div
      v-if="camerasLoading"
      data-testid="vehicles-cameras-loading"
    >
      <Skeleton
        height="320px"
        border-radius="12px"
      />
    </div>

    <Message
      v-else-if="camerasError"
      severity="error"
      :closable="false"
      data-testid="vehicles-cameras-error"
    >
      {{ camerasError }}
    </Message>

    <Message
      v-else-if="cameras.length === 0"
      severity="info"
      :closable="false"
      data-testid="vehicles-no-cameras"
    >
      No cameras yet. Link your Blink account in the General tab first.
    </Message>

    <div
      v-else
      class="vehicle-list"
    >
      <article
        v-for="camera in cameras"
        :key="camera.id"
        class="vehicle-card"
        :data-testid="`vehicle-card-${camera.id}`"
      >
        <div class="vehicle-header">
          <span class="camera-name">{{ camera.name }}</span>
          <ToggleSwitch
            v-if="forms[camera.id].vehicleId"
            v-model="forms[camera.id].enabled"
            :data-testid="`vehicle-enabled-${camera.id}`"
          />
        </div>

        <div
          v-if="forms[camera.id].loading"
          :data-testid="`vehicle-loading-${camera.id}`"
        >
          <Skeleton
            height="160px"
            border-radius="10px"
          />
        </div>

        <template v-else>
          <Message
            v-if="forms[camera.id].error"
            severity="error"
            :closable="false"
            :data-testid="`vehicle-error-${camera.id}`"
          >
            {{ forms[camera.id].error }}
          </Message>

          <div
            v-if="!forms[camera.id].hasReferenceFrame"
            class="no-frame"
          >
            <p class="muted">
              Capture a still frame from this camera's most recent downloaded clip to draw the
              vehicle outline on.
            </p>
            <Button
              label="Capture reference frame"
              icon="pi pi-camera"
              severity="secondary"
              outlined
              :loading="forms[camera.id].capturing"
              :data-testid="`capture-frame-${camera.id}`"
              @click="captureFrame(camera)"
            />
          </div>

          <template v-else>
            <div class="frame-container">
              <img
                :key="forms[camera.id].frameNonce"
                :src="`${vehicleReferenceFrameUrl(camera.id)}?t=${forms[camera.id].frameNonce}`"
                alt="Reference frame for drawing the vehicle outline"
                class="frame-image"
              >
              <svg
                class="outline-svg"
                viewBox="0 0 100 100"
                preserveAspectRatio="none"
                :data-testid="`outline-svg-${camera.id}`"
                @pointerdown="startDrawing(camera.id, $event)"
                @pointermove="continueDrawing(camera.id, $event)"
                @pointerup="stopDrawing(camera.id)"
                @pointerleave="stopDrawing(camera.id)"
              >
                <polygon
                  v-if="forms[camera.id].points.length >= 2"
                  :points="polygonAttr(forms[camera.id].points)"
                  class="outline-polygon"
                />
              </svg>
            </div>
            <div class="outline-toolbar">
              <span class="muted">
                {{ outlineHint(forms[camera.id]) }}
              </span>
              <div class="outline-buttons">
                <Button
                  label="Clear"
                  size="small"
                  text
                  severity="secondary"
                  :disabled="forms[camera.id].points.length === 0"
                  :data-testid="`clear-points-${camera.id}`"
                  @click="clearPoints(camera.id)"
                />
                <Button
                  label="Re-capture frame"
                  size="small"
                  text
                  severity="secondary"
                  :loading="forms[camera.id].capturing"
                  :data-testid="`recapture-frame-${camera.id}`"
                  @click="captureFrame(camera)"
                />
              </div>
            </div>

            <div class="tier-grid">
              <label class="field">
                <span class="field-label">What is it?</span>
                <InputText
                  v-model="forms[camera.id].description"
                  placeholder="e.g. Blue Honda Civic"
                  fluid
                  :data-testid="`vehicle-description-${camera.id}`"
                />
              </label>
              <label class="field">
                <span class="field-label">Real-world length (feet)</span>
                <InputNumber
                  v-model="forms[camera.id].estimatedLengthFeet"
                  :min="0.1"
                  :max="100"
                  :max-fraction-digits="1"
                  fluid
                  :data-testid="`vehicle-length-${camera.id}`"
                />
              </label>
              <label class="field">
                <span class="field-label">Alert within (feet)</span>
                <InputNumber
                  v-model="forms[camera.id].distanceThresholdFeet"
                  :min="0.1"
                  :max="100"
                  :max-fraction-digits="1"
                  fluid
                  :data-testid="`vehicle-threshold-${camera.id}`"
                />
              </label>
            </div>

            <div class="panel-actions">
              <Button
                v-if="forms[camera.id].vehicleId"
                label="Remove protection"
                severity="danger"
                text
                :loading="forms[camera.id].deleting"
                :data-testid="`delete-vehicle-${camera.id}`"
                @click="confirmRemoveVehicle(camera)"
              />
              <Button
                label="Save vehicle"
                :disabled="!canSave(forms[camera.id])"
                :loading="forms[camera.id].saving"
                :data-testid="`save-vehicle-${camera.id}`"
                @click="saveVehicle(camera)"
              />
            </div>
          </template>
        </template>
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

.vehicle-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.vehicle-card {
  padding: 16px;
  border-radius: 10px;
  background: var(--p-surface-50);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.blink-dark .vehicle-card {
  background: color-mix(in srgb, var(--p-surface-800) 55%, transparent);
}

.vehicle-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.camera-name {
  font-size: 0.92rem;
  font-weight: 600;
}

.muted {
  font-size: 0.8rem;
  color: var(--p-surface-500);
  margin: 0;
}

.no-frame {
  display: flex;
  flex-direction: column;
  gap: 10px;
  align-items: flex-start;
}

.frame-container {
  position: relative;
  width: 100%;
  max-width: 480px;
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
  cursor: crosshair;
  touch-action: none;
}

.outline-polygon {
  fill: color-mix(in srgb, var(--p-primary-500) 25%, transparent);
  stroke: var(--p-primary-400);
  stroke-width: 0.5;
}

.outline-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}

.outline-buttons {
  display: flex;
  gap: 4px;
}

.tier-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 14px;
  max-width: 720px;
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
  gap: 8px;
}
</style>
