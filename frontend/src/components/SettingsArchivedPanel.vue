<script setup lang="ts">
import Message from "primevue/message";
import Select from "primevue/select";
import Skeleton from "primevue/skeleton";
import Button from "primevue/button";
import { useToast } from "primevue/usetoast";
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import { ApiError, getStorageIntegrationSettings, updateStorageIntegrationSettings } from "@/api";

import type { StorageBackend, StorageIntegrationSettingsRead } from "@/api";

const toast = useToast();
const router = useRouter();

const loading = ref(true);
const loadError = ref("");
const saving = ref(false);
const saveError = ref("");

const current = ref<StorageIntegrationSettingsRead | null>(null);
const selectedBackend = ref<StorageBackend>("local");

const BACKEND_OPTIONS: { label: string; value: StorageBackend }[] = [
  { label: "Keep on local disk (default)", value: "local" },
  { label: "Amazon S3", value: "s3" },
  { label: "Google Drive", value: "google_drive" },
  { label: "Microsoft OneDrive", value: "onedrive" },
];

async function load(): Promise<void> {
  loading.value = true;
  loadError.value = "";
  try {
    current.value = await getStorageIntegrationSettings();
    selectedBackend.value = current.value.auto_archive_backend;
  } catch (caught) {
    loadError.value =
      caught instanceof ApiError ? caught.message : "Could not load archival settings.";
  } finally {
    loading.value = false;
  }
}

onMounted(load);

/** True once the chosen destination is actually usable - connected for
 * Drive/OneDrive, credentialed for S3. Only called for a non-"local"
 * selection (the template short-circuits on that first), but still
 * handles it for type-safety since selectedBackend's type includes it. */
const selectedBackendIsReady = computed(() => {
  /* v8 ignore next */
  if (!current.value) return false;
  // The template short-circuits before ever reading this computed while
  // selectedBackend is "local" - kept for type-safety since
  // selectedBackend's type includes that value.
  /* v8 ignore next */
  if (selectedBackend.value === "local") {
    /* v8 ignore next */
    return true;
  }
  if (selectedBackend.value === "s3") {
    return current.value.s3_enabled && current.value.s3_credentials_set;
  }
  if (selectedBackend.value === "google_drive") {
    return current.value.google_drive_enabled && current.value.google_drive_connected;
  }
  return current.value.onedrive_enabled && current.value.onedrive_connected;
});

function goToIntegrations(): void {
  void router.push({ name: "integrations" });
}

async function save(): Promise<void> {
  // The Save button only renders once loading has finished and current.value
  // is set - kept as a guard against the property accesses below, not a
  // reachable path from a real click.
  /* v8 ignore next */
  if (!current.value) return;
  saveError.value = "";
  saving.value = true;
  try {
    current.value = await updateStorageIntegrationSettings({
      s3_enabled: current.value.s3_enabled,
      s3_bucket: current.value.s3_bucket,
      s3_region: current.value.s3_region,
      s3_prefix: current.value.s3_prefix,
      google_drive_enabled: current.value.google_drive_enabled,
      google_drive_client_id: current.value.google_drive_client_id,
      google_drive_folder_id: current.value.google_drive_folder_id,
      onedrive_enabled: current.value.onedrive_enabled,
      onedrive_client_id: current.value.onedrive_client_id,
      onedrive_folder_path: current.value.onedrive_folder_path,
      auto_archive_backend: selectedBackend.value,
    });
    toast.add({ severity: "success", summary: "Archival settings saved", life: 2500 });
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
      Archived
    </h3>
    <p class="panel-hint">
      Choose where newly-downloaded clips end up living. Archiving to a cloud provider uploads
      the clip, then removes the local copy — the video stays available on this server just long
      enough for AI analysis to run first.
    </p>

    <div
      v-if="loading"
      data-testid="archived-loading"
    >
      <Skeleton
        height="140px"
        border-radius="12px"
      />
    </div>

    <Message
      v-else-if="loadError"
      severity="error"
      :closable="false"
      data-testid="archived-load-error"
    >
      {{ loadError }}
    </Message>

    <div
      v-else
      class="panel-body"
    >
      <label class="field">
        <span class="field-label">Default destination for new downloads</span>
        <Select
          v-model="selectedBackend"
          :options="BACKEND_OPTIONS"
          option-label="label"
          option-value="value"
          fluid
          data-testid="auto-archive-backend"
        />
      </label>

      <Message
        v-if="selectedBackend !== 'local' && !selectedBackendIsReady"
        severity="warn"
        :closable="false"
        data-testid="archived-not-ready-warning"
      >
        This integration isn't connected yet. New clips will stay local until you
        <a
          href="#"
          data-testid="archived-go-to-integrations"
          @click.prevent="goToIntegrations"
        >set it up on the Integrations page</a>.
      </Message>

      <Message
        v-if="saveError"
        severity="error"
        :closable="false"
        data-testid="archived-save-error"
      >
        {{ saveError }}
      </Message>

      <div class="panel-actions">
        <Button
          label="Save"
          :loading="saving"
          data-testid="save-archived"
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
  gap: 16px;
  max-width: 420px;
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

.panel-actions {
  display: flex;
  justify-content: flex-end;
}
</style>
