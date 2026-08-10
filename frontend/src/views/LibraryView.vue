<script setup lang="ts">
import Button from "primevue/button";
import Checkbox from "primevue/checkbox";
import DatePicker from "primevue/datepicker";
import Paginator, { type PageState } from "primevue/paginator";
import Select from "primevue/select";
import Skeleton from "primevue/skeleton";
import ToggleButton from "primevue/togglebutton";
import { useToast } from "primevue/usetoast";
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import {
  ApiError,
  archiveClips,
  bulkAnalyzeClips,
  bulkDeleteClips,
  deleteClip,
  downloadClipsAsZip,
  getStorageIntegrationSettings,
  listCameras,
  listClips,
  listPeople,
  restoreClips,
} from "@/api";
import ClipCard from "@/components/ClipCard.vue";
import ClipDetailModal from "@/components/ClipDetailModal.vue";
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
import { useDeleteConfirm } from "@/composables/useDeleteConfirm";
import { useAuthStore } from "@/stores/auth";
import { useBlinkStore } from "@/stores/blink";

import type { CameraRead, ClipRead, PersonRead, StorageBackend } from "@/api";

const CLOUD_BACKEND_LABELS: Record<Exclude<StorageBackend, "local">, string> = {
  s3: "Amazon S3",
  google_drive: "Google Drive",
  onedrive: "Microsoft OneDrive",
};

const PAGE_SIZE = 24;

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const blink = useBlinkStore();
const toast = useToast();
const { confirmDelete } = useDeleteConfirm();

const cameras = ref<CameraRead[]>([]);
const cameraNameById = computed(() => {
  const map = new Map<string, string>();
  for (const camera of cameras.value) {
    map.set(camera.id, camera.name);
  }
  return map;
});

const people = ref<PersonRead[]>([]);

const clips = ref<ClipRead[]>([]);
const total = ref(0);
const page = ref(1);
const loading = ref(true);

// Lets links from elsewhere (e.g. the Vehicles overview's "View clips from
// this camera") land here pre-filtered, instead of always opening blank.
const cameraFilter = ref<string | null>(
  typeof route.query.camera_id === "string" ? route.query.camera_id : null,
);
const sinceFilter = ref<Date | null>(null);
const untilFilter = ref<Date | null>(null);
const recognizedPersonFilter = ref<string | null>(null);
const recognizedOnly = ref(false);
const recognizedTotal = ref<number | null>(null);
const filtersActive = computed(
  () =>
    cameraFilter.value !== null ||
    sinceFilter.value !== null ||
    untilFilter.value !== null ||
    recognizedPersonFilter.value !== null ||
    recognizedOnly.value,
);

watch(recognizedPersonFilter, (value) => {
  if (value !== null) {
    recognizedOnly.value = false;
  }
});

watch(recognizedOnly, (value) => {
  if (value) {
    recognizedPersonFilter.value = null;
  }
});

const selected = ref<Set<string>>(new Set());
const selectedCount = computed(() => selected.value.size);
const bulkWorking = ref(false);

const configuredCloudBackends = ref<{ label: string; value: StorageBackend }[]>([]);
const archiveDestination = ref<StorageBackend | null>(null);

async function loadConfiguredCloudBackends(): Promise<void> {
  if (!auth.isAdmin) {
    return;
  }
  try {
    const row = await getStorageIntegrationSettings();
    const options: { label: string; value: StorageBackend }[] = [];
    if (row.s3_enabled && row.s3_credentials_set) {
      options.push({ label: CLOUD_BACKEND_LABELS.s3, value: "s3" });
    }
    if (row.google_drive_enabled && row.google_drive_connected) {
      options.push({ label: CLOUD_BACKEND_LABELS.google_drive, value: "google_drive" });
    }
    if (row.onedrive_enabled && row.onedrive_connected) {
      options.push({ label: CLOUD_BACKEND_LABELS.onedrive, value: "onedrive" });
    }
    configuredCloudBackends.value = options;
    archiveDestination.value = options[0]?.value ?? null;
  } catch {
    configuredCloudBackends.value = [];
  }
}

const openClip = ref<ClipRead | null>(null);
// Which list openClip's position is measured against - normally the visible
// grid's own clips/page, but temporarily a separately-fetched neighboring
// page once Prev/Next crosses a page boundary, so in-modal navigation never
// disturbs the grid page the user was actually browsing.
const modalPageOverride = ref<{ pageNumber: number; items: ClipRead[] } | null>(null);
const statusError = ref(false);

const activeClipList = computed(() => modalPageOverride.value?.items ?? clips.value);
const activeClipListPage = computed(() => modalPageOverride.value?.pageNumber ?? page.value);

const openClipIndex = computed(() =>
  openClip.value ? activeClipList.value.findIndex((c) => c.id === openClip.value!.id) : -1,
);

const openClipAbsoluteIndex = computed(() =>
  openClipIndex.value === -1
    ? -1
    : (activeClipListPage.value - 1) * PAGE_SIZE + openClipIndex.value,
);

const hasPrevClip = computed(() => openClipAbsoluteIndex.value > 0);
const hasNextClip = computed(
  () => openClipAbsoluteIndex.value !== -1 && openClipAbsoluteIndex.value < total.value - 1,
);

async function goToAdjacentClip(direction: "prev" | "next"): Promise<void> {
  const delta = direction === "next" ? 1 : -1;
  const targetIndex = openClipIndex.value + delta;
  if (targetIndex >= 0 && targetIndex < activeClipList.value.length) {
    // eslint-disable-next-line security/detect-object-injection
    openClip.value = activeClipList.value[targetIndex]!;
    return;
  }
  const targetPage = activeClipListPage.value + delta;
  try {
    const response = await listClips({
      camera_id: cameraFilter.value ?? undefined,
      since: sinceFilter.value?.toISOString(),
      until: untilFilter.value?.toISOString(),
      recognized_person_id: recognizedPersonFilter.value ?? undefined,
      has_recognized_person: recognizedOnly.value || undefined,
      page: targetPage,
      page_size: PAGE_SIZE,
    });
    // Guards a race against the total the Prev/Next buttons' disabled state
    // was computed from (e.g. a clip deleted concurrently) - not reachable
    // in the common case, but the server call could still legitimately
    // return fewer items than expected.
    if (response.items.length === 0) return;
    modalPageOverride.value = { pageNumber: targetPage, items: response.items };
    openClip.value =
      direction === "next" ? response.items[0]! : response.items[response.items.length - 1]!;
  } catch (caught) {
    toast.add({
      severity: "error",
      summary: "Could not load the next clip",
      detail: caught instanceof ApiError ? caught.message : "Unexpected error.",
      life: 4000,
    });
  }
}

function closeClip(): void {
  openClip.value = null;
  modalPageOverride.value = null;
}

async function loadCameras(): Promise<void> {
  try {
    cameras.value = await listCameras();
  } catch {
    cameras.value = [];
  }
}

async function loadPeople(): Promise<void> {
  try {
    people.value = await listPeople();
  } catch {
    people.value = [];
  }
}

// A lightweight, filter-independent count for the "Recognized" stat badge —
// page_size: 1 keeps the payload trivial, we only read the response's total.
async function loadRecognizedTotal(): Promise<void> {
  try {
    const response = await listClips({ has_recognized_person: true, page_size: 1 });
    recognizedTotal.value = response.total;
  } catch {
    recognizedTotal.value = null;
  }
}

async function loadClips(): Promise<void> {
  loading.value = true;
  try {
    const response = await listClips({
      camera_id: cameraFilter.value ?? undefined,
      since: sinceFilter.value?.toISOString(),
      until: untilFilter.value?.toISOString(),
      recognized_person_id: recognizedPersonFilter.value ?? undefined,
      has_recognized_person: recognizedOnly.value || undefined,
      page: page.value,
      page_size: PAGE_SIZE,
    });
    clips.value = response.items;
    total.value = response.total;
  } catch (caught) {
    toast.add({
      severity: "error",
      summary: "Could not load clips",
      detail: caught instanceof ApiError ? caught.message : "Unexpected error.",
      life: 4000,
    });
  } finally {
    loading.value = false;
  }
}

async function loadInitial(): Promise<void> {
  loading.value = true;
  statusError.value = false;
  try {
    await blink.refreshStatus();
  } catch {
    statusError.value = true;
    loading.value = false;
    return;
  }
  if (blink.isLinked) {
    await Promise.all([
      loadCameras(),
      loadPeople(),
      loadClips(),
      loadRecognizedTotal(),
      loadConfiguredCloudBackends(),
    ]);
  } else {
    loading.value = false;
  }
}

onMounted(() => {
  void loadInitial();
});

watch([cameraFilter, sinceFilter, untilFilter, recognizedPersonFilter, recognizedOnly], () => {
  page.value = 1;
  selected.value = new Set();
  void loadClips();
});

function onPageChange(event: PageState): void {
  page.value = event.page + 1;
  void loadClips();
}

function clearFilters(): void {
  cameraFilter.value = null;
  sinceFilter.value = null;
  untilFilter.value = null;
  recognizedPersonFilter.value = null;
  recognizedOnly.value = false;
}

function toggleSelected(clipId: string, value: boolean): void {
  const next = new Set(selected.value);
  if (value) {
    next.add(clipId);
  } else {
    next.delete(clipId);
  }
  selected.value = next;
}

function selectAllOnPage(): void {
  selected.value = new Set(clips.value.map((c) => c.id));
}

function clearSelection(): void {
  selected.value = new Set();
}

async function bulkDownload(): Promise<void> {
  bulkWorking.value = true;
  try {
    await downloadClipsAsZip([...selected.value]);
  } catch (caught) {
    toast.add({
      severity: "error",
      summary: "Download failed",
      detail: caught instanceof ApiError ? caught.message : "Unexpected error.",
      life: 4000,
    });
  } finally {
    bulkWorking.value = false;
  }
}

async function performBulkAnalyze(): Promise<void> {
  bulkWorking.value = true;
  try {
    const result = await bulkAnalyzeClips([...selected.value]);
    toast.add({
      severity: result.failed > 0 ? "warn" : "success",
      summary: `Queued ${result.succeeded} clip(s) for analysis`,
      detail: result.failed > 0 ? `${result.failed} could not be queued.` : undefined,
      life: 3500,
    });
    clearSelection();
  } catch (caught) {
    toast.add({
      severity: "error",
      summary: "Bulk analyze failed",
      detail: caught instanceof ApiError ? caught.message : "Unexpected error.",
      life: 4000,
    });
  } finally {
    bulkWorking.value = false;
  }
}

async function performBulkArchive(): Promise<void> {
  // The Archive button only renders once a destination is available -
  // kept as a guard against the call below, not a reachable path from a
  // real click.
  /* v8 ignore next */
  if (!archiveDestination.value) return;
  bulkWorking.value = true;
  try {
    const result = await archiveClips([...selected.value], archiveDestination.value);
    toast.add({
      severity: result.failed > 0 ? "warn" : "success",
      summary: `Queued ${result.succeeded} clip(s) to archive`,
      detail: result.failed > 0 ? `${result.failed} could not be queued.` : undefined,
      life: 3500,
    });
    clearSelection();
  } catch (caught) {
    toast.add({
      severity: "error",
      summary: "Archive failed",
      detail: caught instanceof ApiError ? caught.message : "Unexpected error.",
      life: 4000,
    });
  } finally {
    bulkWorking.value = false;
  }
}

async function performBulkRestore(): Promise<void> {
  bulkWorking.value = true;
  try {
    const result = await restoreClips([...selected.value]);
    toast.add({
      severity: result.failed > 0 ? "warn" : "success",
      summary: `Queued ${result.succeeded} clip(s) to restore`,
      detail: result.failed > 0 ? `${result.failed} were already local.` : undefined,
      life: 3500,
    });
    clearSelection();
  } catch (caught) {
    toast.add({
      severity: "error",
      summary: "Restore failed",
      detail: caught instanceof ApiError ? caught.message : "Unexpected error.",
      life: 4000,
    });
  } finally {
    bulkWorking.value = false;
  }
}

function confirmBulkDelete(): void {
  confirmDelete({
    header: "Delete clips",
    message: `Delete ${selectedCount.value} clip(s)? This cannot be undone.`,
    onAccept: () => void performBulkDelete(),
  });
}

async function performBulkDelete(): Promise<void> {
  bulkWorking.value = true;
  try {
    const result = await bulkDeleteClips([...selected.value]);
    toast.add({
      severity: result.failed > 0 ? "warn" : "success",
      summary: `Deleted ${result.succeeded} clip(s)`,
      detail: result.failed > 0 ? `${result.failed} could not be deleted.` : undefined,
      life: 3500,
    });
    clearSelection();
    await loadClips();
  } catch (caught) {
    toast.add({
      severity: "error",
      summary: "Bulk delete failed",
      detail: caught instanceof ApiError ? caught.message : "Unexpected error.",
      life: 4000,
    });
  } finally {
    bulkWorking.value = false;
  }
}

function confirmSingleDelete(clip: ClipRead): void {
  confirmDelete({
    header: "Delete clip",
    message: "Delete this clip? This cannot be undone.",
    onAccept: () => void performSingleDelete(clip),
  });
}

async function performSingleDelete(clip: ClipRead): Promise<void> {
  try {
    await deleteClip(clip.id);
    closeClip();
    toast.add({ severity: "success", summary: "Clip deleted", life: 2500 });
    await loadClips();
  } catch (caught) {
    toast.add({
      severity: "error",
      summary: "Could not delete clip",
      detail: caught instanceof ApiError ? caught.message : "Unexpected error.",
      life: 4000,
    });
  }
}
</script>

<template>
  <section>
    <PageHeader
      title="Library"
      description="Your synced clips with thumbnails, playback, and download."
    />

    <EmptyState
      v-if="statusError"
      icon="pi pi-exclamation-triangle"
      title="Couldn't check your Blink connection"
      description="We weren't able to reach the server to check your account status. Check your connection and try again."
    >
      <template #actions>
        <Button
          label="Retry"
          icon="pi pi-refresh"
          severity="secondary"
          outlined
          data-testid="retry-status"
          @click="loadInitial"
        />
      </template>
    </EmptyState>

    <EmptyState
      v-else-if="!loading && !blink.isLinked"
      icon="pi pi-images"
      title="Link your Blink account"
      description="Once your Blink account is linked, clips will start syncing automatically, complete with thumbnails."
    >
      <template #actions>
        <Button
          label="Open Settings"
          icon="pi pi-cog"
          severity="secondary"
          outlined
          data-testid="go-settings"
          @click="router.push({ name: 'settings' })"
        />
      </template>
    </EmptyState>

    <template v-else>
      <div class="toolbar">
        <div class="filters">
          <label
            for="camera-filter"
            class="sr-only"
          >Filter by camera</label>
          <Select
            v-model="cameraFilter"
            input-id="camera-filter"
            aria-label="Filter by camera"
            :options="cameras"
            option-label="name"
            option-value="id"
            placeholder="All cameras"
            show-clear
            data-testid="camera-filter"
          />
          <DatePicker
            v-model="sinceFilter"
            placeholder="From date"
            show-icon
            show-button-bar
            data-testid="since-filter"
          />
          <DatePicker
            v-model="untilFilter"
            placeholder="To date"
            show-icon
            show-button-bar
            data-testid="until-filter"
          />
          <label
            v-if="people.length > 0"
            for="recognized-person-filter"
            class="sr-only"
          >Filter by recognized person</label>
          <Select
            v-if="people.length > 0"
            v-model="recognizedPersonFilter"
            input-id="recognized-person-filter"
            aria-label="Filter by recognized person"
            :options="people"
            option-label="name"
            option-value="id"
            placeholder="Anyone recognized"
            show-clear
            data-testid="recognized-person-filter"
          />
          <ToggleButton
            v-if="recognizedTotal !== null && recognizedTotal > 0"
            v-model="recognizedOnly"
            :on-label="`Recognized (${recognizedTotal})`"
            :off-label="`Recognized (${recognizedTotal})`"
            on-icon="pi pi-verified"
            off-icon="pi pi-verified"
            data-testid="recognized-only-toggle"
          />
          <Button
            v-if="filtersActive"
            label="Clear filters"
            severity="secondary"
            text
            data-testid="clear-filters"
            @click="clearFilters"
          />
        </div>
      </div>

      <div
        v-if="selectedCount > 0"
        class="bulk-bar"
        data-testid="bulk-bar"
      >
        <span>{{ selectedCount }} selected</span>
        <div class="bulk-actions">
          <Button
            label="Download"
            icon="pi pi-download"
            severity="secondary"
            outlined
            :loading="bulkWorking"
            data-testid="bulk-download"
            @click="bulkDownload"
          />
          <Button
            label="Analyze"
            icon="pi pi-sparkles"
            severity="secondary"
            outlined
            :loading="bulkWorking"
            data-testid="bulk-analyze"
            @click="performBulkAnalyze"
          />
          <label
            v-if="configuredCloudBackends.length > 0"
            for="bulk-archive-destination"
            class="sr-only"
          >Archive destination</label>
          <Select
            v-if="configuredCloudBackends.length > 0"
            v-model="archiveDestination"
            input-id="bulk-archive-destination"
            aria-label="Archive destination"
            :options="configuredCloudBackends"
            option-label="label"
            option-value="value"
            data-testid="bulk-archive-destination"
          />
          <Button
            v-if="configuredCloudBackends.length > 0"
            label="Archive"
            icon="pi pi-cloud-upload"
            severity="secondary"
            outlined
            :loading="bulkWorking"
            :disabled="!archiveDestination"
            data-testid="bulk-archive"
            @click="performBulkArchive"
          />
          <Button
            label="Restore"
            icon="pi pi-cloud-download"
            severity="secondary"
            outlined
            :loading="bulkWorking"
            data-testid="bulk-restore"
            @click="performBulkRestore"
          />
          <Button
            label="Delete"
            icon="pi pi-trash"
            severity="danger"
            outlined
            :loading="bulkWorking"
            data-testid="bulk-delete"
            @click="confirmBulkDelete"
          />
          <Button
            label="Clear"
            text
            @click="clearSelection"
          />
        </div>
      </div>

      <div
        v-if="loading"
        class="grid"
        data-testid="loading"
      >
        <Skeleton
          v-for="n in 8"
          :key="n"
          height="180px"
          border-radius="12px"
        />
      </div>

      <EmptyState
        v-else-if="clips.length === 0 && !filtersActive"
        icon="pi pi-images"
        title="No clips yet"
        description="Clips will appear here automatically once your cameras sync."
      />

      <EmptyState
        v-else-if="clips.length === 0"
        icon="pi pi-filter-slash"
        title="No clips match these filters"
        description="Try a different camera or date range."
      >
        <template #actions>
          <Button
            label="Clear filters"
            severity="secondary"
            outlined
            @click="clearFilters"
          />
        </template>
      </EmptyState>

      <template v-else>
        <div
          v-if="auth.isAdmin"
          class="select-all-row"
        >
          <Checkbox
            :model-value="selectedCount === clips.length"
            binary
            data-testid="select-all"
            @update:model-value="(v: boolean) => (v ? selectAllOnPage() : clearSelection())"
          />
          <span class="muted">Select all on this page</span>
        </div>

        <div
          class="grid"
          data-testid="clip-grid"
        >
          <ClipCard
            v-for="clip in clips"
            :key="clip.id"
            :clip="clip"
            :camera-name="cameraNameById.get(clip.camera_id) ?? 'Unknown camera'"
            :selected="selected.has(clip.id)"
            :selectable="auth.isAdmin"
            @open="openClip = clip"
            @update:selected="(v: boolean) => toggleSelected(clip.id, v)"
          />
        </div>

        <Paginator
          :rows="PAGE_SIZE"
          :total-records="total"
          :first="(page - 1) * PAGE_SIZE"
          data-testid="paginator"
          @page="onPageChange"
        />
      </template>
    </template>

    <ClipDetailModal
      :clip="openClip"
      :camera-name="openClip ? (cameraNameById.get(openClip.camera_id) ?? 'Unknown camera') : ''"
      :can-manage="auth.isAdmin"
      :has-prev="hasPrevClip"
      :has-next="hasNextClip"
      @close="closeClip"
      @delete="openClip && confirmSingleDelete(openClip)"
      @prev="goToAdjacentClip('prev')"
      @next="goToAdjacentClip('next')"
    />
  </section>
</template>

<style scoped>
.toolbar {
  margin-bottom: 16px;
}

.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}

.bulk-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
  padding: 10px 16px;
  margin-bottom: 14px;
  border-radius: 10px;
  background: color-mix(in srgb, var(--p-primary-500) 12%, transparent);
  font-size: 0.88rem;
  font-weight: 600;
}

.bulk-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.select-all-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.muted {
  font-size: 0.82rem;
  color: var(--p-surface-500);
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 16px;
}
</style>
