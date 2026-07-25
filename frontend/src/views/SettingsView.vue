<script setup lang="ts">
import Button from "primevue/button";
import InputText from "primevue/inputtext";
import Message from "primevue/message";
import Password from "primevue/password";
import Select from "primevue/select";
import SelectButton from "primevue/selectbutton";
import Tab from "primevue/tab";
import TabList from "primevue/tablist";
import TabPanel from "primevue/tabpanel";
import TabPanels from "primevue/tabpanels";
import Tabs from "primevue/tabs";
import { useToast } from "primevue/usetoast";
import { onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import { ApiError, getStorageSettings, updateMe, updateStorageSettings } from "@/api";
import BlinkAccountPanel from "@/components/BlinkAccountPanel.vue";
import PageHeader from "@/components/PageHeader.vue";
import SettingsAiProviderPanel from "@/components/SettingsAiProviderPanel.vue";
import SettingsAlertsPanel from "@/components/SettingsAlertsPanel.vue";
import SettingsBiometricsPanel from "@/components/SettingsBiometricsPanel.vue";
import SettingsCamerasPanel from "@/components/SettingsCamerasPanel.vue";
import SettingsUsersPanel from "@/components/SettingsUsersPanel.vue";
import SettingsVehiclesPanel from "@/components/SettingsVehiclesPanel.vue";
import { useTheme } from "@/composables/useTheme";
import { useAuthStore } from "@/stores/auth";

const MIN_PASSWORD_LENGTH = 12;

const auth = useAuthStore();
const toast = useToast();
const route = useRoute();
const { isDark, setDark } = useTheme();

const ADMIN_TABS = ["users", "ai", "biometrics", "cameras", "vehicles", "alerts"];
const requestedTab = typeof route.query.tab === "string" ? route.query.tab : "general";
const activeTab = ref(
  auth.isAdmin && ADMIN_TABS.includes(requestedTab) ? requestedTab : "general",
);

const displayName = ref("");
const timezone = ref("UTC");
const savingProfile = ref(false);

const newPassword = ref("");
const confirmPassword = ref("");
const passwordError = ref("");
const savingPassword = ref(false);

// "UTC" is a valid Intl timeZone but, oddly, isn't in the IANA-backed
// supportedValuesOf() enumeration — add it explicitly so it's selectable
// (new accounts default to it) rather than showing a blank field.
const timezones = ["UTC", ...Intl.supportedValuesOf("timeZone")];

const themeOptions = [
  { label: "Dark", value: true },
  { label: "Light", value: false },
];

onMounted(() => {
  if (auth.user) {
    displayName.value = auth.user.display_name;
    timezone.value = auth.user.timezone;
  }
});

async function saveProfile(): Promise<void> {
  savingProfile.value = true;
  try {
    auth.user = await updateMe({ display_name: displayName.value, timezone: timezone.value });
    toast.add({ severity: "success", summary: "Profile saved", life: 2500 });
  } catch (caught) {
    toast.add({
      severity: "error",
      summary: "Could not save profile",
      detail: caught instanceof ApiError ? caught.message : "Unexpected error.",
      life: 4000,
    });
  } finally {
    savingProfile.value = false;
  }
}

async function savePassword(): Promise<void> {
  passwordError.value = "";
  if (newPassword.value.length < MIN_PASSWORD_LENGTH) {
    passwordError.value = `Password must be at least ${MIN_PASSWORD_LENGTH} characters.`;
    return;
  }
  if (newPassword.value !== confirmPassword.value) {
    passwordError.value = "Passwords do not match.";
    return;
  }
  savingPassword.value = true;
  try {
    await updateMe({ password: newPassword.value });
    newPassword.value = "";
    confirmPassword.value = "";
    toast.add({ severity: "success", summary: "Password updated", life: 2500 });
  } catch (caught) {
    passwordError.value = caught instanceof ApiError ? caught.message : "Unexpected error.";
  } finally {
    savingPassword.value = false;
  }
}

const storageDir = ref("");
const storageIsDefault = ref(true);
const savingStorage = ref(false);
const storageError = ref("");

onMounted(async () => {
  if (auth.user?.is_superuser) {
    try {
      const settings = await getStorageSettings();
      storageDir.value = settings.storage_dir;
      storageIsDefault.value = settings.is_default;
    } catch {
      // Non-fatal — the field just starts blank; saving will surface errors.
    }
  }
});

async function saveStorageDir(): Promise<void> {
  storageError.value = "";
  savingStorage.value = true;
  try {
    const settings = await updateStorageSettings({ storage_dir: storageDir.value || null });
    storageDir.value = settings.storage_dir;
    storageIsDefault.value = settings.is_default;
    toast.add({ severity: "success", summary: "Storage location saved", life: 2500 });
  } catch (caught) {
    storageError.value = caught instanceof ApiError ? caught.message : "Unexpected error.";
  } finally {
    savingStorage.value = false;
  }
}
</script>

<template>
  <section>
    <PageHeader
      title="Settings"
      description="Your profile, security, appearance, and — for admins — Blink, AI, biometrics, cameras, vehicles, alerts, and household access."
    />

    <Tabs
      v-model:value="activeTab"
      lazy
    >
      <TabList>
        <Tab value="general">
          General
        </Tab>
        <Tab
          v-if="auth.isAdmin"
          value="users"
        >
          Users
        </Tab>
        <Tab
          v-if="auth.isAdmin"
          value="ai"
        >
          AI Provider
        </Tab>
        <Tab
          v-if="auth.isAdmin"
          value="biometrics"
        >
          Biometrics
        </Tab>
        <Tab
          v-if="auth.isAdmin"
          value="cameras"
        >
          Cameras
        </Tab>
        <Tab
          v-if="auth.isAdmin"
          value="vehicles"
        >
          Vehicles
        </Tab>
        <Tab
          v-if="auth.isAdmin"
          value="alerts"
        >
          Alerts
        </Tab>
      </TabList>
      <TabPanels>
        <TabPanel value="general">
          <div class="panels">
            <article class="panel">
              <h3 class="panel-title">
                Profile
              </h3>
              <p class="panel-hint">
                Shown around the app and used for report timestamps.
              </p>
              <div class="panel-body">
                <label class="field">
                  <span class="field-label">Display name</span>
                  <InputText
                    v-model="displayName"
                    fluid
                    data-testid="display-name"
                  />
                </label>
                <label class="field">
                  <span class="field-label">Timezone</span>
                  <Select
                    v-model="timezone"
                    :options="timezones"
                    filter
                    fluid
                    data-testid="timezone"
                  />
                </label>
                <div class="panel-actions">
                  <Button
                    label="Save profile"
                    :loading="savingProfile"
                    data-testid="save-profile"
                    @click="saveProfile"
                  />
                </div>
              </div>
            </article>

            <article class="panel">
              <h3 class="panel-title">
                Security
              </h3>
              <p class="panel-hint">
                Use at least {{ MIN_PASSWORD_LENGTH }} characters.
              </p>
              <div class="panel-body">
                <label class="field">
                  <span class="field-label">New password</span>
                  <Password
                    v-model="newPassword"
                    toggle-mask
                    fluid
                    data-testid="new-password"
                  />
                </label>
                <label class="field">
                  <span class="field-label">Confirm new password</span>
                  <Password
                    v-model="confirmPassword"
                    :feedback="false"
                    toggle-mask
                    fluid
                    data-testid="confirm-password"
                  />
                </label>
                <p
                  v-if="passwordError"
                  class="field-error"
                  data-testid="password-error"
                >
                  {{ passwordError }}
                </p>
                <div class="panel-actions">
                  <Button
                    label="Update password"
                    severity="secondary"
                    :loading="savingPassword"
                    data-testid="save-password"
                    @click="savePassword"
                  />
                </div>
              </div>
            </article>

            <article class="panel">
              <h3 class="panel-title">
                Appearance
              </h3>
              <p class="panel-hint">
                Dark is the default for a security console.
              </p>
              <div class="panel-body">
                <SelectButton
                  :model-value="isDark"
                  :options="themeOptions"
                  option-label="label"
                  option-value="value"
                  :allow-empty="false"
                  data-testid="theme-select"
                  @update:model-value="setDark"
                />
              </div>
            </article>

            <BlinkAccountPanel />

            <article
              v-if="auth.user?.is_superuser"
              class="panel"
            >
              <h3 class="panel-title">
                Storage
              </h3>
              <p class="panel-hint">
                Where downloaded clips are saved on this server.
              </p>
              <div class="panel-body">
                <label class="field">
                  <span class="field-label">Clip storage directory</span>
                  <InputText
                    v-model="storageDir"
                    placeholder="/data/clips"
                    fluid
                    data-testid="storage-dir"
                  />
                </label>
                <p class="muted">
                  {{ storageIsDefault ? "Using the default from server configuration." : "Custom location." }}
                  Changing this does not move already-downloaded clips.
                </p>
                <Message
                  v-if="storageError"
                  severity="error"
                  :closable="false"
                  data-testid="storage-error"
                >
                  {{ storageError }}
                </Message>
                <div class="panel-actions">
                  <Button
                    label="Save"
                    :loading="savingStorage"
                    data-testid="save-storage"
                    @click="saveStorageDir"
                  />
                </div>
              </div>
            </article>

            <article class="panel">
              <h3 class="panel-title">
                About
              </h3>
              <p class="panel-hint">
                Blink AI Security is built on
                <a
                  href="https://github.com/fronzbot/blinkpy"
                  target="_blank"
                  rel="noopener noreferrer"
                >blinkpy</a>, the unofficial Blink API client this project relies on for all Blink
                communication.
              </p>
              <a
                class="about-link"
                href="https://github.com/brianbaggs35/blink_downloader"
                target="_blank"
                rel="noopener noreferrer"
              >
                <i
                  class="pi pi-github"
                  aria-hidden="true"
                />
                View source on GitHub
              </a>
            </article>
          </div>
        </TabPanel>

        <TabPanel
          v-if="auth.isAdmin"
          value="users"
        >
          <SettingsUsersPanel />
        </TabPanel>

        <TabPanel
          v-if="auth.isAdmin"
          value="ai"
        >
          <SettingsAiProviderPanel />
        </TabPanel>

        <TabPanel
          v-if="auth.isAdmin"
          value="biometrics"
        >
          <SettingsBiometricsPanel />
        </TabPanel>

        <TabPanel
          v-if="auth.isAdmin"
          value="cameras"
        >
          <SettingsCamerasPanel />
        </TabPanel>

        <TabPanel
          v-if="auth.isAdmin"
          value="vehicles"
        >
          <SettingsVehiclesPanel />
        </TabPanel>

        <TabPanel
          v-if="auth.isAdmin"
          value="alerts"
        >
          <SettingsAlertsPanel />
        </TabPanel>
      </TabPanels>
    </Tabs>
  </section>
</template>

<style scoped>
.panels {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 16px;
  align-items: start;
}

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
}

.panel-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
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

.field-error {
  margin: 0;
  font-size: 0.82rem;
  color: var(--p-red-500);
}

.panel-actions {
  display: flex;
  justify-content: flex-end;
}

.muted {
  margin: 0;
  font-size: 0.82rem;
  color: var(--p-surface-500);
}

.about-link {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--p-primary-600);
  text-decoration: none;
}

.blink-dark .about-link {
  color: var(--p-primary-300);
}

.about-link:hover {
  text-decoration: underline;
}
</style>
