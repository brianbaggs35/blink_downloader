<script setup lang="ts">
import Button from "primevue/button";
import InputNumber from "primevue/inputnumber";
import Message from "primevue/message";
import Select from "primevue/select";
import Skeleton from "primevue/skeleton";
import { useToast } from "primevue/usetoast";
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import {
  ApiError,
  getStorageIntegrationSettings,
  getStorageSettings,
  updateStorageIntegrationSettings,
  updateStorageSettings,
} from "@/api";

import type {
  StorageBackend,
  StorageIntegrationSettingsRead,
  StorageSettingsRead,
} from "@/api";

const toast = useToast();
const router = useRouter();

const loading = ref(true);
const loadError = ref("");
const saving = ref(false);
const saveError = ref("");

const localSettings = ref<StorageSettingsRead | null>(null);
const integrationSettings = ref<StorageIntegrationSettingsRead | null>(null);

const selectedBackend = ref<StorageBackend>("local");
const archiveAfterDays = ref(0);
const quotaGb = ref<number | null>(null);

const GB_BYTES = 1024 ** 3;

function bytesToGb(bytes: number): number {
  return Math.round((bytes / GB_BYTES) * 100) / 100;
}

async function load(): Promise<void> {
  loading.value = true;
  loadError.value = "";
  try {
    const [local, integrations] = await Promise.all([
      getStorageSettings(),
      getStorageIntegrationSettings(),
    ]);
    localSettings.value = local;
    integrationSettings.value = integrations;
    // Self-heals a destination that's since been disconnected (revoked
    // credentials, deleted app registration, ...) back to Local, rather
    // than leaving the Select bound to a value that's no longer among its
    // own options (PrimeVue would just render it blank).
    selectedBackend.value = backendOptions.value.some(
      (option) => option.value === integrations.auto_archive_backend,
    )
      ? integrations.auto_archive_backend
      : "local";
    archiveAfterDays.value = integrations.auto_archive_after_days;
    quotaGb.value = local.local_storage_quota_bytes ? bytesToGb(local.local_storage_quota_bytes) : null;
  } catch (caught) {
    loadError.value =
      caught instanceof ApiError ? caught.message : "Could not load storage settings.";
  } finally {
    loading.value = false;
  }
}

onMounted(load);

const BACKEND_OPTIONS_ALL: { label: string; value: StorageBackend }[] = [
  { label: "Local disk (default)", value: "local" },
  { label: "Amazon S3", value: "s3" },
  { label: "Google Drive", value: "google_drive" },
  { label: "Microsoft OneDrive", value: "onedrive" },
];

/** Only offers a cloud provider once it's actually connected - local is
 * always offered. */
const backendOptions = computed(() => {
  const settings = integrationSettings.value;
  /* v8 ignore next */
  if (!settings) return BACKEND_OPTIONS_ALL.slice(0, 1);
  return BACKEND_OPTIONS_ALL.filter((option) => {
    if (option.value === "local") return true;
    if (option.value === "s3") return settings.s3_enabled && settings.s3_credentials_set;
    if (option.value === "google_drive") {
      return settings.google_drive_enabled && settings.google_drive_connected;
    }
    return settings.onedrive_enabled && settings.onedrive_connected;
  });
});

function goToStorageTab(): void {
  void router.push({ name: "storage" });
}

function goToIntegrations(): void {
  void router.push({ name: "integrations" });
}

async function save(): Promise<void> {
  // The form (the only caller) only renders once both settings objects are
  // loaded - kept as a guard against the property accesses below, not a
  // reachable path from a real click.
  /* v8 ignore next */
  if (!localSettings.value || !integrationSettings.value) return;
  saveError.value = "";
  saving.value = true;
  try {
    const s = integrationSettings.value;
    integrationSettings.value = await updateStorageIntegrationSettings({
      s3_enabled: s.s3_enabled,
      s3_bucket: s.s3_bucket,
      s3_region: s.s3_region,
      s3_prefix: s.s3_prefix,
      google_drive_enabled: s.google_drive_enabled,
      google_drive_client_id: s.google_drive_client_id,
      google_drive_folder_id: s.google_drive_folder_id,
      onedrive_enabled: s.onedrive_enabled,
      onedrive_client_id: s.onedrive_client_id,
      onedrive_folder_path: s.onedrive_folder_path,
      auto_archive_backend: selectedBackend.value,
      auto_archive_after_days: archiveAfterDays.value,
    });
    // Echoes storage_dir back exactly as-is (null when still on the
    // default, the resolved value otherwise) - this panel never edits the
    // folder itself (that's the Storage tab's job), so a quota-only save
    // here must never silently reset it.
    localSettings.value = await updateStorageSettings({
      storage_dir: localSettings.value.is_default ? null : localSettings.value.storage_dir,
      local_storage_quota_bytes: quotaGb.value ? Math.round(quotaGb.value * GB_BYTES) : null,
    });
    toast.add({ severity: "success", summary: "Storage settings saved", life: 2500 });
  } catch (caught) {
    saveError.value = caught instanceof ApiError ? caught.message : "Unexpected error.";
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <article class="panel">
    <h3 class="panel-title">
      Storage
    </h3>
    <p class="panel-hint">
      Where clips live day to day, and - separately - where and when older clips move to cold
      storage. Pick a folder for either one on the
      <a
        href="#"
        data-testid="storage-go-to-storage-tab"
        @click.prevent="goToStorageTab"
      >Storage tab</a>.
    </p>

    <div
      v-if="loading"
      data-testid="storage-settings-loading"
    >
      <Skeleton
        height="220px"
        border-radius="12px"
      />
    </div>

    <Message
      v-else-if="loadError"
      severity="error"
      :closable="false"
      data-testid="storage-settings-load-error"
    >
      {{ loadError }}
    </Message>

    <div
      v-else
      class="panel-body"
    >
      <section class="subsection">
        <h4 class="subsection-title">
          Local disk
        </h4>
        <p class="current-value">
          <i
            class="pi pi-folder"
            aria-hidden="true"
          />
          <span data-testid="current-local-folder">{{ localSettings?.storage_dir }}</span>
        </p>
        <label class="field">
          <span class="field-label">Quota (GB, optional)</span>
          <InputNumber
            v-model="quotaGb"
            :min="0.1"
            :max-fraction-digits="2"
            placeholder="No limit"
            fluid
            data-testid="storage-quota-gb"
          />
        </label>
        <p class="muted">
          A soft budget shown as a gauge on the Storage tab - not enforced, nothing is deleted or
          blocked automatically when you go over it.
        </p>
      </section>

      <section class="subsection">
        <h4 class="subsection-title">
          Archiving
        </h4>
        <label class="field">
          <span class="field-label">Move older clips to</span>
          <Select
            v-model="selectedBackend"
            :options="backendOptions"
            option-label="label"
            option-value="value"
            fluid
            data-testid="auto-archive-backend"
          />
        </label>
        <label class="field">
          <span class="field-label">Days to keep clips locally first</span>
          <InputNumber
            v-model="archiveAfterDays"
            :min="0"
            :max="365"
            show-buttons
            fluid
            data-testid="auto-archive-after-days"
          />
        </label>
        <p class="muted">
          0 archives a clip immediately once it's done with local disk (right after download, or
          after AI analysis if that's on). A cloud destination uploads the clip, then removes the
          local copy.
        </p>

        <Message
          v-if="backendOptions.length === 1"
          severity="info"
          :closable="false"
          data-testid="storage-no-providers-connected"
        >
          No cloud provider is connected yet.
          <a
            href="#"
            data-testid="storage-go-to-integrations"
            @click.prevent="goToIntegrations"
          >Connect one</a>
          to archive clips off this server.
        </Message>
      </section>

      <Message
        v-if="saveError"
        severity="error"
        :closable="false"
        data-testid="storage-settings-save-error"
      >
        {{ saveError }}
      </Message>

      <div class="panel-actions">
        <Button
          label="Save"
          :loading="saving"
          data-testid="save-storage-settings"
          @click="save"
        />
      </div>
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

.panel-body {
  display: flex;
  flex-direction: column;
  gap: 22px;
  max-width: 460px;
}

.subsection {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.subsection-title {
  margin: 0;
  font-size: 0.82rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--p-surface-500);
}

.blink-dark .subsection-title {
  color: var(--p-surface-400);
}

.current-value {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  padding: 8px 12px;
  border-radius: 8px;
  font-size: 0.85rem;
  font-family: var(--font-mono, monospace);
  background: var(--p-surface-50);
  overflow-wrap: anywhere;
}

.blink-dark .current-value {
  background: color-mix(in srgb, var(--p-surface-900) 70%, transparent);
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field-label {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--p-surface-600);
}

.blink-dark .field-label {
  color: var(--p-surface-300);
}

.muted {
  margin: 0;
  font-size: 0.8rem;
  color: var(--p-surface-500);
}

.panel-actions {
  display: flex;
  justify-content: flex-end;
}
</style>
