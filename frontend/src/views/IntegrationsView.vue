<script setup lang="ts">
import Button from "primevue/button";
import Checkbox from "primevue/checkbox";
import Dialog from "primevue/dialog";
import IconField from "primevue/iconfield";
import InputIcon from "primevue/inputicon";
import InputText from "primevue/inputtext";
import Message from "primevue/message";
import Password from "primevue/password";
import SelectButton from "primevue/selectbutton";
import Skeleton from "primevue/skeleton";
import Tag from "primevue/tag";
import ToggleSwitch from "primevue/toggleswitch";
import { useToast } from "primevue/usetoast";
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import {
  ApiError,
  getStorageIntegrationSettings,
  googleDriveOAuthStartUrl,
  onedriveOAuthStartUrl,
  testStorageIntegrations,
  updateStorageIntegrationSettings,
} from "@/api";
import BrandIcon from "@/components/BrandIcon.vue";
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";

import type { StorageIntegrationSettingsRead, StorageTestResult } from "@/api";
import type { BrandName } from "@/components/BrandIcon.vue";

type ProviderKey = "s3" | "google_drive" | "onedrive";

/** S3 has no accurate real-brand icon readily available under a permissive
 * license (unlike Drive/OneDrive - see BrandIcon.vue) - pi-amazon (a generic
 * company mark, not a product-specific one) is the closest reasonable
 * option. */
type IntegrationIcon = { kind: "class"; value: string } | { kind: "brand"; value: BrandName };

interface IntegrationDef {
  key: ProviderKey;
  name: string;
  category: string;
  icon: IntegrationIcon;
  description: string;
}

const INTEGRATIONS: IntegrationDef[] = [
  {
    key: "s3",
    name: "Amazon S3",
    category: "Storage",
    icon: { kind: "class", value: "pi pi-amazon" },
    description: "Archive downloaded clips to an S3 bucket you own.",
  },
  {
    key: "google_drive",
    name: "Google Drive",
    category: "Storage",
    icon: { kind: "brand", value: "google_drive" },
    description: "Archive downloaded clips to your Google Drive.",
  },
  {
    key: "onedrive",
    name: "Microsoft OneDrive",
    category: "Storage",
    icon: { kind: "brand", value: "onedrive" },
    description: "Archive downloaded clips to your OneDrive.",
  },
];

const toast = useToast();
const route = useRoute();

const loading = ref(true);
const loadError = ref("");
const current = ref<StorageIntegrationSettingsRead | null>(null);

async function load(): Promise<void> {
  loading.value = true;
  loadError.value = "";
  try {
    current.value = await getStorageIntegrationSettings();
  } catch (caught) {
    loadError.value =
      caught instanceof ApiError ? caught.message : "Could not load integrations.";
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  void load();
  const connected = route.query.connected;
  const error = route.query.error;
  if (typeof connected === "string") {
    const def = INTEGRATIONS.find((i) => i.key === connected);
    toast.add({
      severity: "success",
      summary: `${def?.name ?? connected} connected`,
      life: 3000,
    });
  }
  if (typeof error === "string") {
    const def = INTEGRATIONS.find((i) => i.key === error);
    toast.add({
      severity: "error",
      summary: `Could not connect ${def?.name ?? error}`,
      detail: "The connection attempt failed or was cancelled. Please try again.",
      life: 5000,
    });
  }
});

// ------------------------------------------------------------ search/filter

const searchText = ref("");
const categoryOptions = computed(() => ["All", ...new Set(INTEGRATIONS.map((i) => i.category))]);
const selectedCategory = ref("All");

const filteredIntegrations = computed(() =>
  INTEGRATIONS.filter(
    (i) =>
      (selectedCategory.value === "All" || i.category === selectedCategory.value) &&
      i.name.toLowerCase().includes(searchText.value.trim().toLowerCase()),
  ),
);

// --------------------------------------------------------------- connection

function isEnabled(key: ProviderKey): boolean {
  // Cards (the only callers, via statusSeverity/statusLabel) only render
  // once loading has finished and current.value is set.
  /* v8 ignore next */
  if (!current.value) return false;
  if (key === "s3") return current.value.s3_enabled;
  if (key === "google_drive") return current.value.google_drive_enabled;
  return current.value.onedrive_enabled;
}

function isConnected(key: ProviderKey): boolean {
  /* v8 ignore next */
  if (!current.value) return false;
  if (key === "s3") return current.value.s3_enabled && current.value.s3_credentials_set;
  if (key === "google_drive") {
    return current.value.google_drive_enabled && current.value.google_drive_connected;
  }
  return current.value.onedrive_enabled && current.value.onedrive_connected;
}

function statusSeverity(key: ProviderKey): "success" | "warn" | "secondary" {
  if (isConnected(key)) return "success";
  if (isEnabled(key)) return "warn";
  return "secondary";
}

function statusLabel(key: ProviderKey): string {
  if (isConnected(key)) return "Connected";
  if (isEnabled(key)) return "Needs attention";
  return "Not connected";
}

// -------------------------------------------------------------- expansion

const expandedKey = ref<ProviderKey | null>(null);

const s3Enabled = ref(false);
const s3Bucket = ref("");
const s3Region = ref("");
const s3AccessKeyInput = ref("");
const s3SecretKeyInput = ref("");
const s3ClearCredentials = ref(false);

const driveEnabled = ref(false);
const driveClientId = ref("");
const driveClientSecretInput = ref("");
const driveClientSecretClear = ref(false);

const onedriveEnabled = ref(false);
const onedriveClientId = ref("");
const onedriveClientSecretInput = ref("");
const onedriveClientSecretClear = ref(false);

function resetFormsFromCurrent(): void {
  // Only called from toggleExpanded, itself only reachable once cards (and
  // so current.value) are rendered.
  /* v8 ignore next */
  if (!current.value) return;
  s3Enabled.value = current.value.s3_enabled;
  s3Bucket.value = current.value.s3_bucket ?? "";
  s3Region.value = current.value.s3_region ?? "";
  s3AccessKeyInput.value = "";
  s3SecretKeyInput.value = "";
  s3ClearCredentials.value = false;

  driveEnabled.value = current.value.google_drive_enabled;
  driveClientId.value = current.value.google_drive_client_id ?? "";
  driveClientSecretInput.value = "";
  driveClientSecretClear.value = false;

  onedriveEnabled.value = current.value.onedrive_enabled;
  onedriveClientId.value = current.value.onedrive_client_id ?? "";
  onedriveClientSecretInput.value = "";
  onedriveClientSecretClear.value = false;
}

function toggleExpanded(key: ProviderKey): void {
  if (expandedKey.value === key) {
    expandedKey.value = null;
    return;
  }
  resetFormsFromCurrent();
  expandedKey.value = key;
}

function resolvedSecret(input: string, clear: boolean): string | null {
  if (input) return input;
  return clear ? "" : null;
}

const saving = ref(false);
const saveError = ref("");

async function saveProvider(key: ProviderKey): Promise<void> {
  // The form (the only caller) only renders once current.value is set.
  /* v8 ignore next */
  if (!current.value) return;
  saveError.value = "";
  saving.value = true;
  try {
    current.value = await updateStorageIntegrationSettings({
      s3_enabled: key === "s3" ? s3Enabled.value : current.value.s3_enabled,
      s3_bucket: key === "s3" ? s3Bucket.value || null : current.value.s3_bucket,
      s3_region: key === "s3" ? s3Region.value || null : current.value.s3_region,
      // Folder/prefix selection lives exclusively on the Storage tab now -
      // this page only ever edits credentials, so always echo it back.
      s3_prefix: current.value.s3_prefix,
      s3_access_key_id:
        key === "s3" ? resolvedSecret(s3AccessKeyInput.value, s3ClearCredentials.value) : null,
      s3_secret_access_key:
        key === "s3" ? resolvedSecret(s3SecretKeyInput.value, s3ClearCredentials.value) : null,
      google_drive_enabled: key === "google_drive" ? driveEnabled.value : current.value.google_drive_enabled,
      google_drive_client_id:
        key === "google_drive" ? driveClientId.value || null : current.value.google_drive_client_id,
      google_drive_client_secret:
        key === "google_drive"
          ? resolvedSecret(driveClientSecretInput.value, driveClientSecretClear.value)
          : null,
      google_drive_folder_id: current.value.google_drive_folder_id,
      onedrive_enabled: key === "onedrive" ? onedriveEnabled.value : current.value.onedrive_enabled,
      onedrive_client_id:
        key === "onedrive" ? onedriveClientId.value || null : current.value.onedrive_client_id,
      onedrive_client_secret:
        key === "onedrive"
          ? resolvedSecret(onedriveClientSecretInput.value, onedriveClientSecretClear.value)
          : null,
      onedrive_folder_path: current.value.onedrive_folder_path,
      auto_archive_backend: current.value.auto_archive_backend,
      auto_archive_after_days: current.value.auto_archive_after_days,
    });
    resetFormsFromCurrent();
    toast.add({ severity: "success", summary: "Integration saved", life: 2500 });
  } catch (caught) {
    saveError.value = caught instanceof ApiError ? caught.message : "Unexpected error.";
  } finally {
    saving.value = false;
  }
}

// -------------------------------------------------------------- test/connect

const testing = ref(false);
const testResults = ref<Partial<Record<ProviderKey, StorageTestResult>>>({});

async function runTest(): Promise<void> {
  testing.value = true;
  try {
    const response = await testStorageIntegrations();
    testResults.value = {
      s3: response.s3 ?? undefined,
      google_drive: response.google_drive ?? undefined,
      onedrive: response.onedrive ?? undefined,
    };
  } catch (caught) {
    toast.add({
      severity: "error",
      summary: "Could not run connection tests",
      detail: caught instanceof ApiError ? caught.message : "Unexpected error.",
      life: 4000,
    });
  } finally {
    testing.value = false;
  }
}

function connectOAuthProvider(key: "google_drive" | "onedrive"): void {
  window.location.href = key === "google_drive" ? googleDriveOAuthStartUrl() : onedriveOAuthStartUrl();
}

// -------------------------------------------------------------------- help

const helpOpenFor = ref<ProviderKey | null>(null);
const redirectOrigin = window.location.origin;
</script>

<template>
  <section>
    <PageHeader
      title="Integrations"
      description="Connect cloud storage providers so archived clips have somewhere to go. More integrations are on the way."
    />

    <div class="toolbar">
      <IconField class="search">
        <InputIcon class="pi pi-search" />
        <InputText
          v-model="searchText"
          placeholder="Search integrations"
          fluid
          data-testid="integrations-search"
        />
      </IconField>
      <SelectButton
        v-model="selectedCategory"
        :options="categoryOptions"
        :allow-empty="false"
        data-testid="integrations-category-filter"
      />
      <Button
        label="Test all connections"
        severity="secondary"
        outlined
        :loading="testing"
        data-testid="test-all-integrations"
        @click="runTest"
      />
    </div>

    <div
      v-if="loading"
      class="grid"
      data-testid="integrations-loading"
    >
      <Skeleton
        v-for="n in 3"
        :key="n"
        height="140px"
        border-radius="14px"
      />
    </div>

    <Message
      v-else-if="loadError"
      severity="error"
      :closable="false"
      data-testid="integrations-load-error"
    >
      {{ loadError }}
    </Message>

    <EmptyState
      v-else-if="filteredIntegrations.length === 0"
      icon="pi pi-search"
      title="No integrations match"
      description="Try a different search term or category."
    />

    <div
      v-else
      class="grid"
    >
      <article
        v-for="integration in filteredIntegrations"
        :key="integration.key"
        class="card"
        :data-testid="`integration-card-${integration.key}`"
      >
        <div class="card-header">
          <div class="card-icon">
            <i
              v-if="integration.icon.kind === 'class'"
              :class="integration.icon.value"
            />
            <BrandIcon
              v-else
              :name="integration.icon.value"
            />
          </div>
          <div class="card-heading">
            <h3>{{ integration.name }}</h3>
            <Tag
              :value="integration.category"
              severity="secondary"
              class="category-tag"
            />
          </div>
          <Button
            icon="pi pi-question-circle"
            severity="secondary"
            text
            rounded
            aria-label="How to connect"
            :data-testid="`integration-help-${integration.key}`"
            @click="helpOpenFor = integration.key"
          />
        </div>
        <p class="card-description">
          {{ integration.description }}
        </p>
        <div class="card-footer">
          <Tag
            :value="statusLabel(integration.key)"
            :severity="statusSeverity(integration.key)"
            :data-testid="`integration-status-${integration.key}`"
          />
          <Button
            :label="expandedKey === integration.key ? 'Close' : 'Configure'"
            severity="secondary"
            outlined
            size="small"
            :data-testid="`integration-configure-${integration.key}`"
            @click="toggleExpanded(integration.key)"
          />
        </div>

        <div
          v-if="testResults[integration.key]"
          class="test-result"
          :class="testResults[integration.key]!.ok ? 'ok' : 'fail'"
          :data-testid="`integration-test-result-${integration.key}`"
        >
          <i :class="testResults[integration.key]!.ok ? 'pi pi-check-circle' : 'pi pi-times-circle'" />
          {{ testResults[integration.key]!.detail }}
        </div>

        <form
          v-if="expandedKey === integration.key"
          class="config-form"
          :data-testid="`integration-form-${integration.key}`"
          @submit.prevent="saveProvider(integration.key)"
        >
          <Message
            severity="info"
            :closable="false"
            class="form-hint"
          >
            Once this is enabled and connected, pick which folder new clips archive to on the
            <RouterLink :to="{ name: 'storage' }">
              Storage tab
            </RouterLink>.
          </Message>

          <template v-if="integration.key === 's3'">
            <div class="toggle-row">
              <ToggleSwitch
                v-model="s3Enabled"
                data-testid="s3-enabled"
              />
              <p class="toggle-label">
                Enabled
              </p>
            </div>
            <label class="field">
              <span class="field-label">Bucket name</span>
              <InputText
                v-model="s3Bucket"
                fluid
                data-testid="s3-bucket"
              />
            </label>
            <label class="field">
              <span class="field-label">Region</span>
              <InputText
                v-model="s3Region"
                placeholder="us-east-1"
                fluid
                data-testid="s3-region"
              />
            </label>
            <label class="field">
              <span class="field-label">Access key ID</span>
              <Password
                v-model="s3AccessKeyInput"
                :feedback="false"
                toggle-mask
                fluid
                :placeholder="current?.s3_credentials_set ? '•••••••• (saved — leave blank to keep)' : ''"
                data-testid="s3-access-key"
              />
            </label>
            <label class="field">
              <span class="field-label">Secret access key</span>
              <Password
                v-model="s3SecretKeyInput"
                :feedback="false"
                toggle-mask
                fluid
                :placeholder="current?.s3_credentials_set ? '•••••••• (saved — leave blank to keep)' : ''"
                data-testid="s3-secret-key"
              />
            </label>
            <label
              v-if="current?.s3_credentials_set"
              class="clear-key"
            >
              <Checkbox
                v-model="s3ClearCredentials"
                binary
                data-testid="s3-clear-credentials"
              />
              Remove the saved credentials on next save
            </label>
          </template>

          <template v-else-if="integration.key === 'google_drive'">
            <div class="toggle-row">
              <ToggleSwitch
                v-model="driveEnabled"
                data-testid="drive-enabled"
              />
              <p class="toggle-label">
                Enabled
              </p>
            </div>
            <label class="field">
              <span class="field-label">OAuth client ID</span>
              <InputText
                v-model="driveClientId"
                fluid
                data-testid="drive-client-id"
              />
            </label>
            <label class="field">
              <span class="field-label">OAuth client secret</span>
              <Password
                v-model="driveClientSecretInput"
                :feedback="false"
                toggle-mask
                fluid
                :placeholder="
                  current?.google_drive_client_secret_set
                    ? '•••••••• (saved — leave blank to keep)'
                    : ''
                "
                data-testid="drive-client-secret"
              />
            </label>
            <label
              v-if="current?.google_drive_client_secret_set"
              class="clear-key"
            >
              <Checkbox
                v-model="driveClientSecretClear"
                binary
                data-testid="drive-clear-secret"
              />
              Remove the saved client secret on next save
            </label>
            <Button
              label="Connect with Google"
              icon="pi pi-google"
              :disabled="!driveClientId || !current?.google_drive_client_secret_set"
              severity="secondary"
              data-testid="drive-connect"
              @click="connectOAuthProvider('google_drive')"
            />
          </template>

          <template v-else>
            <div class="toggle-row">
              <ToggleSwitch
                v-model="onedriveEnabled"
                data-testid="onedrive-enabled"
              />
              <p class="toggle-label">
                Enabled
              </p>
            </div>
            <label class="field">
              <span class="field-label">Application (client) ID</span>
              <InputText
                v-model="onedriveClientId"
                fluid
                data-testid="onedrive-client-id"
              />
            </label>
            <label class="field">
              <span class="field-label">Client secret</span>
              <Password
                v-model="onedriveClientSecretInput"
                :feedback="false"
                toggle-mask
                fluid
                :placeholder="
                  current?.onedrive_client_secret_set
                    ? '•••••••• (saved — leave blank to keep)'
                    : ''
                "
                data-testid="onedrive-client-secret"
              />
            </label>
            <label
              v-if="current?.onedrive_client_secret_set"
              class="clear-key"
            >
              <Checkbox
                v-model="onedriveClientSecretClear"
                binary
                data-testid="onedrive-clear-secret"
              />
              Remove the saved client secret on next save
            </label>
            <Button
              label="Connect with Microsoft"
              icon="pi pi-microsoft"
              :disabled="!onedriveClientId || !current?.onedrive_client_secret_set"
              severity="secondary"
              data-testid="onedrive-connect"
              @click="connectOAuthProvider('onedrive')"
            />
          </template>

          <Message
            v-if="saveError"
            severity="error"
            :closable="false"
          >
            {{ saveError }}
          </Message>

          <div class="form-actions">
            <Button
              type="button"
              label="Test connection"
              severity="secondary"
              outlined
              :loading="testing"
              :data-testid="`integration-test-${integration.key}`"
              @click="runTest"
            />
            <Button
              type="submit"
              label="Save"
              :loading="saving"
              :data-testid="`integration-save-${integration.key}`"
            />
          </div>
        </form>
      </article>
    </div>

    <Dialog
      :visible="helpOpenFor === 's3'"
      modal
      header="Connecting Amazon S3"
      data-testid="help-dialog-s3"
      @update:visible="helpOpenFor = null"
    >
      <ol class="help-steps">
        <li>In the AWS Console, create an S3 bucket (any region) to hold archived clips.</li>
        <li>
          Create an IAM user (or role) with a policy granting <code>s3:PutObject</code>,
          <code>s3:GetObject</code>, and <code>s3:DeleteObject</code> on that bucket.
        </li>
        <li>Generate an access key for that user.</li>
        <li>Enter the bucket name, region, access key ID, and secret access key here, then save.</li>
      </ol>
    </Dialog>

    <Dialog
      :visible="helpOpenFor === 'google_drive'"
      modal
      header="Connecting Google Drive"
      data-testid="help-dialog-google_drive"
      @update:visible="helpOpenFor = null"
    >
      <ol class="help-steps">
        <li>
          In the
          <a
            href="https://console.cloud.google.com/apis/credentials"
            target="_blank"
            rel="noopener"
          >Google Cloud Console</a>, create an OAuth 2.0 Client ID of type "Web application".
        </li>
        <li>
          Add this exact redirect URI to the client:
          <code>{{ redirectOrigin }}/api/settings/storage-integrations/google-drive/oauth/callback</code>
        </li>
        <li>Copy the Client ID and Client Secret into the form here and save.</li>
        <li>Click "Connect with Google" and approve access on Google's own sign-in screen.</li>
      </ol>
    </Dialog>

    <Dialog
      :visible="helpOpenFor === 'onedrive'"
      modal
      header="Connecting OneDrive"
      data-testid="help-dialog-onedrive"
      @update:visible="helpOpenFor = null"
    >
      <ol class="help-steps">
        <li>
          In the
          <a
            href="https://entra.microsoft.com"
            target="_blank"
            rel="noopener"
          >Microsoft Entra admin center</a>, register a new application.
        </li>
        <li>
          Add this exact redirect URI (platform: Web):
          <code>{{ redirectOrigin }}/api/settings/storage-integrations/onedrive/oauth/callback</code>
        </li>
        <li>Under API permissions, add the delegated <code>Files.ReadWrite</code> Graph permission.</li>
        <li>Create a client secret, then copy the Application (client) ID and secret into the form here and save.</li>
        <li>Click "Connect with Microsoft" and approve access on Microsoft's own sign-in screen.</li>
      </ol>
    </Dialog>
  </section>
</template>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 20px;
}

.search {
  flex: 1;
  min-width: 220px;
}

.form-hint {
  margin: 0;
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}

.card {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 20px;
  border-radius: 14px;
  border: 1px solid var(--p-surface-200);
  background: var(--p-surface-0);
}

.blink-dark .card {
  border-color: var(--p-surface-800);
  background: color-mix(in srgb, var(--p-surface-900) 60%, transparent);
}

.card-header {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.card-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border-radius: 12px;
  font-size: 1.3rem;
  background: var(--p-surface-100);
  color: var(--p-surface-700);
  flex-shrink: 0;
}

.blink-dark .card-icon {
  background: color-mix(in srgb, var(--p-surface-800) 70%, transparent);
  color: var(--p-surface-200);
}

.card-heading {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.card-heading h3 {
  margin: 0;
  font-size: 1rem;
  font-weight: 700;
}

.category-tag {
  align-self: flex-start;
  font-size: 0.68rem;
}

.card-description {
  margin: 0;
  font-size: 0.85rem;
  color: var(--p-surface-500);
  flex: 1;
}

.card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.test-result {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 8px;
  font-size: 0.82rem;
  background: var(--p-surface-50);
}

.blink-dark .test-result {
  background: color-mix(in srgb, var(--p-surface-800) 55%, transparent);
}

.test-result.ok {
  color: var(--p-green-600);
}

.test-result.fail {
  color: var(--p-red-500);
}

.config-form {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding-top: 14px;
  border-top: 1px solid var(--p-surface-200);
}

.blink-dark .config-form {
  border-color: var(--p-surface-800);
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.toggle-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.toggle-label {
  margin: 0;
  font-size: 0.9rem;
  font-weight: 600;
}

.field-label {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--p-surface-600);
}

.blink-dark .field-label {
  color: var(--p-surface-300);
}

.clear-key {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.8rem;
  color: var(--p-surface-600);
}

.blink-dark .clear-key {
  color: var(--p-surface-300);
}

.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.help-steps {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding-left: 20px;
  margin: 0;
  max-width: 60ch;
}

.help-steps code {
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--p-surface-100);
  font-size: 0.82em;
  word-break: break-all;
}

.blink-dark .help-steps code {
  background: color-mix(in srgb, var(--p-surface-800) 70%, transparent);
}
</style>
