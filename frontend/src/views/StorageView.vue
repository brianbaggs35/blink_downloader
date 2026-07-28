<script setup lang="ts">
import Button from "primevue/button";
import Message from "primevue/message";
import Skeleton from "primevue/skeleton";
import Tag from "primevue/tag";
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import { ApiError, getStorageIntegrationSettings, getStorageSummary } from "@/api";
import PageHeader from "@/components/PageHeader.vue";
import { useFormatting } from "@/composables/useFormatting";
import { useAuthStore } from "@/stores/auth";

import type {
  BackendStorageSummary,
  StorageBackend,
  StorageIntegrationSettingsRead,
  StorageSummaryResponse,
} from "@/api";

interface BackendMeta {
  label: string;
  icon: string;
}

const BACKEND_META: Record<StorageBackend, BackendMeta> = {
  local: { label: "Local disk", icon: "pi pi-server" },
  s3: { label: "Amazon S3", icon: "pi pi-amazon" },
  google_drive: { label: "Google Drive", icon: "pi pi-google" },
  onedrive: { label: "Microsoft OneDrive", icon: "pi pi-microsoft" },
};

const BACKENDS: StorageBackend[] = ["local", "s3", "google_drive", "onedrive"];

const router = useRouter();
const auth = useAuthStore();
const { formatFileSize } = useFormatting();

const loading = ref(true);
const loadError = ref("");
const summary = ref<StorageSummaryResponse | null>(null);
const integrations = ref<StorageIntegrationSettingsRead | null>(null);

async function load(): Promise<void> {
  loading.value = true;
  loadError.value = "";
  try {
    // Integration connection status is admin-only (same as the Integrations
    // page itself) - a viewer still gets real per-backend usage numbers,
    // just without the "is this actually connected" detail on top.
    const [summaryResult, integrationsResult] = await Promise.all([
      getStorageSummary(),
      auth.isAdmin ? getStorageIntegrationSettings() : Promise.resolve(null),
    ]);
    summary.value = summaryResult;
    integrations.value = integrationsResult;
  } catch (caught) {
    loadError.value = caught instanceof ApiError ? caught.message : "Could not load storage usage.";
  } finally {
    loading.value = false;
  }
}

onMounted(load);

function backendRow(backend: StorageBackend): BackendStorageSummary {
  return (
    summary.value?.by_backend.find((row) => row.backend === backend) ?? {
      backend,
      clip_count: 0,
      total_bytes: 0,
    }
  );
}

/** Local always counts as "connected" - there's nothing to set up. Only
 * called for a non-"local" backend (both call sites in the template
 * short-circuit on that first), but still handles it for type-safety
 * since StorageBackend's type includes that value. */
function isConnected(backend: StorageBackend): boolean {
  /* v8 ignore next */
  if (!integrations.value) return false;
  if (backend === "s3") return integrations.value.s3_enabled && integrations.value.s3_credentials_set;
  if (backend === "google_drive") {
    return integrations.value.google_drive_enabled && integrations.value.google_drive_connected;
  }
  // Only "onedrive" remains, given the "local"/"s3"/"google_drive" returns above.
  return integrations.value.onedrive_enabled && integrations.value.onedrive_connected;
}

/** Which folder a connected provider is actually using, for display next to
 * its card - null when there's nothing meaningful to show (local disk, not
 * connected, or a viewer with no integrations detail at all). */
function folderLabel(backend: StorageBackend): string | null {
  if (backend === "local" || !integrations.value || !isConnected(backend)) return null;
  if (backend === "s3") {
    if (!integrations.value.s3_bucket) return null;
    return integrations.value.s3_prefix
      ? `${integrations.value.s3_bucket}/${integrations.value.s3_prefix}`
      : integrations.value.s3_bucket;
  }
  if (backend === "google_drive") {
    return integrations.value.google_drive_folder_id
      ? `Folder ID: ${integrations.value.google_drive_folder_id}`
      : "My Drive (root)";
  }
  // Only "onedrive" remains, given the "local"/"s3"/"google_drive" returns above.
  return integrations.value.onedrive_folder_path || "BlinkClips";
}

const autoArchiveLabel = computed(() => {
  if (!integrations.value || integrations.value.auto_archive_backend === "local") {
    return "New downloads stay on local disk.";
  }
  return `New downloads auto-archive to ${BACKEND_META[integrations.value.auto_archive_backend].label}.`;
});

function goToArchivedSettings(): void {
  void router.push({ name: "settings", query: { tab: "archived" } });
}

function goToIntegrations(): void {
  void router.push({ name: "integrations" });
}

function goToLibrary(): void {
  void router.push({ name: "library" });
}
</script>

<template>
  <section>
    <PageHeader
      title="Storage"
      description="Where your clips live today, and where new ones will end up."
    >
      <template #actions>
        <Button
          label="Refresh"
          icon="pi pi-refresh"
          severity="secondary"
          outlined
          :loading="loading"
          data-testid="refresh-storage"
          @click="load"
        />
      </template>
    </PageHeader>

    <div
      v-if="loading"
      class="grid"
      data-testid="storage-loading"
    >
      <Skeleton
        v-for="n in 4"
        :key="n"
        height="140px"
        border-radius="14px"
      />
    </div>

    <Message
      v-else-if="loadError"
      severity="error"
      :closable="false"
      data-testid="storage-load-error"
    >
      {{ loadError }}
    </Message>

    <template v-else-if="summary">
      <div class="overview">
        <article class="overview-tile">
          <span class="overview-value">{{ summary.total_clips }}</span>
          <span class="overview-label">Downloaded clips</span>
        </article>
        <article class="overview-tile">
          <span class="overview-value">{{ formatFileSize(summary.total_bytes) }}</span>
          <span class="overview-label">Total size on disk and archived</span>
        </article>
      </div>

      <div
        v-if="auth.isAdmin"
        class="auto-archive-row"
        data-testid="auto-archive-summary"
      >
        <i
          class="pi pi-info-circle"
          aria-hidden="true"
        />
        <span>{{ autoArchiveLabel }}</span>
        <a
          href="#"
          data-testid="storage-go-to-archived"
          @click.prevent="goToArchivedSettings"
        >Change this</a>
      </div>

      <div
        class="grid"
        data-testid="backend-grid"
      >
        <article
          v-for="backend in BACKENDS"
          :key="backend"
          class="backend-card"
          :data-testid="`backend-card-${backend}`"
        >
          <div class="backend-header">
            <i
              :class="BACKEND_META[backend].icon"
              aria-hidden="true"
            />
            <span class="backend-name">{{ BACKEND_META[backend].label }}</span>
            <Tag
              v-if="backend !== 'local' && auth.isAdmin"
              :value="isConnected(backend) ? 'Connected' : 'Not connected'"
              :severity="isConnected(backend) ? 'success' : 'secondary'"
              :data-testid="`backend-status-${backend}`"
            />
          </div>
          <div
            v-if="folderLabel(backend)"
            class="backend-folder"
            :data-testid="`backend-folder-${backend}`"
            :title="folderLabel(backend)!"
          >
            <i
              class="pi pi-folder"
              aria-hidden="true"
            />
            <span>{{ folderLabel(backend) }}</span>
          </div>
          <div class="backend-stats">
            <div>
              <span class="stat-value">{{ backendRow(backend).clip_count }}</span>
              <span class="stat-label">clip(s)</span>
            </div>
            <div>
              <span class="stat-value">{{ formatFileSize(backendRow(backend).total_bytes) }}</span>
              <span class="stat-label">on this backend</span>
            </div>
          </div>
          <Button
            v-if="backend !== 'local' && auth.isAdmin && !isConnected(backend)"
            label="Connect"
            icon="pi pi-arrow-right"
            text
            size="small"
            :data-testid="`backend-connect-${backend}`"
            @click="goToIntegrations"
          />
        </article>
      </div>

      <div class="footer-hint">
        <p class="muted">
          Archive or restore individual clips, or a whole selection at once, from the
          <a
            href="#"
            data-testid="storage-go-to-library"
            @click.prevent="goToLibrary"
          >Library</a>'s bulk actions.
        </p>
      </div>
    </template>
  </section>
</template>

<style scoped>
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 14px;
  margin-bottom: 20px;
}

.overview {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 14px;
  margin-bottom: 14px;
}

.overview-tile {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 18px 20px;
  border-radius: 14px;
  border: 1px solid var(--p-surface-200);
  background: var(--p-surface-0);
}

.blink-dark .overview-tile {
  border-color: var(--p-surface-800);
  background: color-mix(in srgb, var(--p-surface-900) 60%, transparent);
}

.overview-value {
  font-size: 1.7rem;
  font-weight: 700;
  letter-spacing: -0.02em;
}

.overview-label {
  font-size: 0.8rem;
  color: var(--p-surface-500);
}

.auto-archive-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 10px 14px;
  margin-bottom: 20px;
  border-radius: 10px;
  font-size: 0.85rem;
  color: var(--p-surface-600);
  background: var(--p-surface-50);
}

.blink-dark .auto-archive-row {
  color: var(--p-surface-300);
  background: color-mix(in srgb, var(--p-surface-900) 60%, transparent);
}

.backend-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 18px 20px;
  border-radius: 14px;
  border: 1px solid var(--p-surface-200);
  background: var(--p-surface-0);
}

.blink-dark .backend-card {
  border-color: var(--p-surface-800);
  background: color-mix(in srgb, var(--p-surface-900) 60%, transparent);
}

.backend-header {
  display: flex;
  align-items: center;
  gap: 10px;
}

.backend-header i {
  font-size: 1.1rem;
  color: var(--p-surface-500);
}

.backend-name {
  font-weight: 700;
  font-size: 0.92rem;
  flex: 1;
}

.backend-folder {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  font-size: 0.78rem;
  color: var(--p-surface-500);
}

.backend-folder i {
  flex-shrink: 0;
}

.backend-folder span {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.backend-stats {
  display: flex;
  gap: 20px;
}

.backend-stats .stat-value {
  display: block;
  font-size: 1.25rem;
  font-weight: 700;
  letter-spacing: -0.01em;
}

.backend-stats .stat-label {
  font-size: 0.75rem;
  color: var(--p-surface-500);
}

.footer-hint {
  margin-top: 4px;
}

.muted {
  margin: 0;
  font-size: 0.85rem;
  color: var(--p-surface-500);
}
</style>
