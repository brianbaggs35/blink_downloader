<script setup lang="ts">
import Button from "primevue/button";
import Column from "primevue/column";
import DataTable from "primevue/datatable";
import Message from "primevue/message";
import Skeleton from "primevue/skeleton";
import Tag from "primevue/tag";
import { useToast } from "primevue/usetoast";
import { computed, onMounted, onUnmounted, reactive, ref } from "vue";

import {
  ApiError,
  deleteSyncModuleLocalStorageItem,
  downloadSyncModuleLocalStorageItem,
  listSyncModuleLocalStorageItems,
  listSyncModules,
  refreshSyncModuleLocalStorage,
  syncModuleLocalStorageItemFileUrl,
} from "@/api";
import { useDeleteConfirm } from "@/composables/useDeleteConfirm";
import { useFormatting } from "@/composables/useFormatting";
import { useAuthStore } from "@/stores/auth";

import type { LocalItemStatus, LocalStorageStatus, SyncModuleLocalItemRead } from "@/api";

// Polls while anything is actively in flight (a manifest refresh, or a
// clip being prepared/downloaded on the Sync Module's own side) - short
// enough to feel live, not so short it hammers the server for what's
// fundamentally a slow, external, request-then-wait flow.
const POLL_INTERVAL_MS = 3000;

const props = defineProps<{ syncModuleId: string }>();

const toast = useToast();
const auth = useAuthStore();
const { confirmDelete } = useDeleteConfirm();
const { formatDateTime, formatFileSize } = useFormatting();

interface StatusInfo {
  status: LocalStorageStatus;
  refreshedAt: string | null;
  lastError: string | null;
}

const items = ref<SyncModuleLocalItemRead[]>([]);
const statusInfo = ref<StatusInfo | null>(null);
const loading = ref(true);
const loadError = ref("");
const refreshingManifest = ref(false);

// Local-only, purely to bridge the gap between clicking an action and the
// next refetch reflecting it - most needed for delete, which (unlike
// download's real PREPARING/DOWNLOADING server states) has no transitional
// status of its own: the row either disappears (succeeded) or comes back
// as ERROR (failed), nothing in between.
const busyItemIds = reactive(new Set<string>());

let pollTimer: ReturnType<typeof setInterval> | undefined;

function isSettling(): boolean {
  return (
    statusInfo.value?.status === "refreshing" ||
    items.value.some((item) => item.status === "preparing" || item.status === "downloading") ||
    busyItemIds.size > 0
  );
}

// There's no single-sync-module GET route - fetching the full list and
// finding this one is the only way to see local_storage_status/
// manifest_refreshed_at/last_error after triggering a refresh. Fine at
// realistic scale (a household has a handful of sync modules at most).
async function refreshAll(): Promise<void> {
  const [freshItems, allSyncModules] = await Promise.all([
    listSyncModuleLocalStorageItems(props.syncModuleId),
    listSyncModules(),
  ]);
  for (const id of [...busyItemIds]) {
    const match = freshItems.find((item) => item.id === id);
    if (!match || (match.status !== "preparing" && match.status !== "downloading")) {
      busyItemIds.delete(id);
    }
  }
  items.value = freshItems;
  const match = allSyncModules.find((s) => s.id === props.syncModuleId);
  if (match) {
    statusInfo.value = {
      status: match.local_storage_status,
      refreshedAt: match.local_storage_manifest_refreshed_at,
      lastError: match.local_storage_last_error,
    };
  }
}

// force is for right after triggering an action (refresh/download/delete):
// the request that kicked it off has already resolved (the job is merely
// *enqueued*), so isSettling() reading the state from just before the
// worker has even started - or already raced past REFRESHING straight to a
// terminal status matching some *other* pre-click value, like a download
// button's own "available" starting state - would otherwise skip polling
// altogether and leave the row showing stale status forever. Forcing one
// poll cycle guarantees a fresh look after the (typically sub-second)
// worker run has actually landed, regardless of what this snapshot saw.
function ensurePolling({ force = false }: { force?: boolean } = {}): void {
  if (pollTimer || (!force && !isSettling())) return;
  pollTimer = setInterval(() => {
    void (async () => {
      await refreshAll();
      if (!isSettling() && pollTimer) {
        clearInterval(pollTimer);
        pollTimer = undefined;
      }
    })();
  }, POLL_INTERVAL_MS);
}

onUnmounted(() => clearInterval(pollTimer));

/** Admin-only (refreshSyncModuleLocalStorage is admin-gated server-side
 * too) and only for a Sync Module that's never had a manifest refresh
 * complete - a household member shouldn't have to know a "Refresh files"
 * button exists just to see what's already on their own USB drive. Refires
 * on every mount until a refresh actually succeeds (harmless: each attempt
 * is its own bounded, rate-reasonable request, and the backend's own
 * periodic refresh job retries independently regardless of whether anyone
 * has this tab open). */
function shouldAutoRefresh(): boolean {
  return (
    auth.isAdmin &&
    statusInfo.value !== null &&
    statusInfo.value.refreshedAt === null &&
    statusInfo.value.status !== "refreshing"
  );
}

async function load(): Promise<void> {
  loading.value = true;
  loadError.value = "";
  try {
    await refreshAll();
    if (shouldAutoRefresh()) {
      await triggerRefresh();
    } else {
      ensurePolling();
    }
  } catch (caught) {
    loadError.value =
      caught instanceof ApiError ? caught.message : "Could not load local storage.";
  } finally {
    loading.value = false;
  }
}

onMounted(load);

async function triggerRefresh(): Promise<void> {
  refreshingManifest.value = true;
  try {
    await refreshSyncModuleLocalStorage(props.syncModuleId);
    toast.add({
      severity: "success",
      summary: "Refreshing files from the Sync Module…",
      life: 2500,
    });
  } catch (caught) {
    toast.add({
      severity: "error",
      summary: "Could not start refresh",
      detail: caught instanceof ApiError ? caught.message : "Unexpected error.",
      life: 4000,
    });
  } finally {
    refreshingManifest.value = false;
    await refreshAll();
    ensurePolling({ force: true });
  }
}

async function triggerDownload(item: SyncModuleLocalItemRead): Promise<void> {
  busyItemIds.add(item.id);
  try {
    await downloadSyncModuleLocalStorageItem(props.syncModuleId, item.id);
    toast.add({ severity: "success", summary: "Queued for download", life: 2500 });
  } catch (caught) {
    toast.add({
      severity: "error",
      summary: "Could not queue download",
      detail: caught instanceof ApiError ? caught.message : "Unexpected error.",
      life: 4000,
    });
  } finally {
    await refreshAll();
    ensurePolling({ force: true });
  }
}

function confirmDeleteItem(item: SyncModuleLocalItemRead): void {
  confirmDelete({
    header: "Delete from Sync Module",
    message: `Delete this clip (${item.camera_name}) from the Sync Module's USB storage? This can't be undone.`,
    onAccept: () => void triggerDelete(item),
  });
}

async function triggerDelete(item: SyncModuleLocalItemRead): Promise<void> {
  busyItemIds.add(item.id);
  try {
    await deleteSyncModuleLocalStorageItem(props.syncModuleId, item.id);
    toast.add({ severity: "success", summary: "Queued for deletion", life: 2500 });
  } catch (caught) {
    toast.add({
      severity: "error",
      summary: "Could not queue deletion",
      detail: caught instanceof ApiError ? caught.message : "Unexpected error.",
      life: 4000,
    });
  } finally {
    await refreshAll();
    ensurePolling({ force: true });
  }
}

function isBusy(item: SyncModuleLocalItemRead): boolean {
  return (
    busyItemIds.has(item.id) || item.status === "preparing" || item.status === "downloading"
  );
}

function statusLabel(info: StatusInfo): string {
  if (info.status === "idle" && !info.refreshedAt) {
    return "Not checked yet";
  }
  switch (info.status) {
    case "refreshing":
      return "Refreshing";
    case "error":
      return "Error";
    default:
      return "Idle";
  }
}

function statusSeverity(info: StatusInfo): "warn" | "danger" | "secondary" | "info" {
  if (info.status === "idle" && !info.refreshedAt) {
    return "info";
  }
  switch (info.status) {
    case "refreshing":
      return "warn";
    case "error":
      return "danger";
    default:
      return "secondary";
  }
}

/** Distinguishes "never checked" from "checked, found nothing" from
 * "still checking" from "checking failed" - a bare "No files found yet"
 * regardless of which of these was true was the exact confusion behind the
 * "files aren't showing up" report this replaces. */
function emptyStateMessage(): string {
  const info = statusInfo.value;
  if (!info) {
    return "No files found yet.";
  }
  if (info.status === "refreshing") {
    return info.refreshedAt
      ? "Refreshing files from the Sync Module… this can take up to about 90 seconds."
      : "Checking this Sync Module's USB storage for the first time… this can take up to about 90 seconds.";
  }
  if (info.status === "error") {
    return "Couldn't check for files - see the error above, then try Refresh files again.";
  }
  if (!info.refreshedAt) {
    return auth.isAdmin
      ? "Not checked yet - click Refresh files to look for what's on this Sync Module's USB storage."
      : "Not checked yet.";
  }
  return "No files found on this Sync Module's USB storage.";
}

function itemStatusLabel(status: LocalItemStatus): string {
  switch (status) {
    case "available":
      return "Available";
    case "preparing":
      return "Preparing";
    case "downloading":
      return "Downloading";
    case "downloaded":
      return "Downloaded";
    default:
      return "Error";
  }
}

function itemStatusSeverity(status: LocalItemStatus): "info" | "warn" | "success" | "danger" {
  switch (status) {
    case "available":
      return "info";
    case "preparing":
    case "downloading":
      return "warn";
    case "downloaded":
      return "success";
    default:
      return "danger";
  }
}

const lastRefreshedLabel = computed(() => {
  const refreshedAt = statusInfo.value?.refreshedAt;
  return refreshedAt ? `Last refreshed: ${formatDateTime(refreshedAt)}` : "Never refreshed yet";
});
</script>

<template>
  <div class="local-storage">
    <div class="browser-header">
      <div class="browser-title">
        <h4>Local (USB) storage</h4>
        <Tag
          v-if="statusInfo"
          :value="statusLabel(statusInfo)"
          :severity="statusSeverity(statusInfo)"
          data-testid="local-storage-status"
        />
      </div>
      <div class="browser-header-actions">
        <span class="muted">{{ lastRefreshedLabel }}</span>
        <Button
          v-if="auth.isAdmin"
          label="Refresh files"
          icon="pi pi-refresh"
          size="small"
          outlined
          :loading="refreshingManifest"
          data-testid="refresh-local-storage"
          @click="triggerRefresh"
        />
      </div>
    </div>

    <Message
      v-if="statusInfo?.status === 'error' && statusInfo.lastError"
      severity="error"
      :closable="false"
      data-testid="local-storage-status-error"
    >
      {{ statusInfo.lastError }}
    </Message>

    <Skeleton
      v-if="loading"
      height="140px"
      border-radius="10px"
      data-testid="local-storage-loading"
    />
    <Message
      v-else-if="loadError"
      severity="error"
      :closable="false"
      data-testid="local-storage-load-error"
    >
      {{ loadError }}
    </Message>

    <div
      v-else
      class="table-scroll"
    >
      <DataTable
        :value="items"
        data-key="id"
        size="small"
        data-testid="local-storage-table"
      >
        <template #empty>
          <p
            class="muted"
            data-testid="local-storage-empty-message"
          >
            {{ emptyStateMessage() }}
          </p>
        </template>
        <Column
          field="camera_name"
          header="Camera"
        >
          <template #body="{ data }: { data: SyncModuleLocalItemRead }">
            <span>{{ data.camera_name }}</span>
            <span
              v-if="!data.camera_id"
              class="muted"
            > (unmatched)</span>
          </template>
        </Column>
        <Column header="Recorded">
          <template #body="{ data }: { data: SyncModuleLocalItemRead }">
            {{ formatDateTime(data.recorded_at) }}
          </template>
        </Column>
        <Column header="Size">
          <template #body="{ data }: { data: SyncModuleLocalItemRead }">
            {{ formatFileSize(data.size_bytes) }}
          </template>
        </Column>
        <Column header="Status">
          <template #body="{ data }: { data: SyncModuleLocalItemRead }">
            <Tag
              :value="itemStatusLabel(data.status)"
              :severity="itemStatusSeverity(data.status)"
              :data-testid="`item-status-${data.id}`"
            />
            <p
              v-if="data.status === 'error' && data.last_error"
              class="muted item-error"
            >
              {{ data.last_error }}
            </p>
          </template>
        </Column>
        <Column
          v-if="auth.isAdmin"
          header="Actions"
        >
          <template #body="{ data }: { data: SyncModuleLocalItemRead }">
            <div class="item-actions">
              <Button
                v-if="data.status === 'available' || data.status === 'error'"
                label="Download"
                icon="pi pi-download"
                size="small"
                text
                :loading="isBusy(data)"
                :data-testid="`download-item-${data.id}`"
                @click="triggerDownload(data)"
              />
              <span
                v-else-if="data.status === 'preparing' || data.status === 'downloading'"
                class="muted"
              >
                {{ data.status === "preparing" ? "Preparing…" : "Downloading…" }}
              </span>
              <template v-if="data.status === 'downloaded'">
                <Button
                  as="a"
                  :href="syncModuleLocalStorageItemFileUrl(syncModuleId, data.id)"
                  label="Download"
                  icon="pi pi-download"
                  size="small"
                  text
                  :data-testid="`open-item-${data.id}`"
                />
                <Button
                  label="Delete"
                  icon="pi pi-trash"
                  size="small"
                  text
                  severity="danger"
                  :loading="isBusy(data)"
                  :data-testid="`delete-item-${data.id}`"
                  @click="confirmDeleteItem(data)"
                />
              </template>
            </div>
          </template>
        </Column>
      </DataTable>
    </div>
  </div>
</template>

<style scoped>
.local-storage {
  padding-top: 8px;
  border-top: 1px solid var(--p-surface-200);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.blink-dark .local-storage {
  border-color: var(--p-surface-800);
}

.table-scroll {
  overflow-x: auto;
}

.browser-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.browser-title {
  display: flex;
  align-items: center;
  gap: 10px;
}

.browser-title h4 {
  margin: 0;
  font-size: 0.8rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  color: var(--p-surface-500);
}

.browser-header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.muted {
  font-size: 0.8rem;
  color: var(--p-surface-500);
  margin: 0;
}

.item-error {
  margin-top: 2px;
  font-size: 0.75rem;
}

.item-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}

.item-actions :deep(a) {
  text-decoration: none;
}
</style>
