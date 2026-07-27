<script setup lang="ts">
import Button from "primevue/button";
import InputNumber from "primevue/inputnumber";
import InputText from "primevue/inputtext";
import Message from "primevue/message";
import Password from "primevue/password";
import Select from "primevue/select";
import SelectButton from "primevue/selectbutton";
import { useToast } from "primevue/usetoast";
import { computed, nextTick, onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import {
  ApiError,
  getBlinkSyncSettings,
  getStorageSettings,
  updateBlinkSyncSettings,
  updateMe,
  updateStorageSettings,
} from "@/api";
import BlinkAccountPanel from "@/components/BlinkAccountPanel.vue";
import PageHeader from "@/components/PageHeader.vue";
import SettingsAboutPanel from "@/components/SettingsAboutPanel.vue";
import SettingsAiProviderPanel from "@/components/SettingsAiProviderPanel.vue";
import SettingsAlertsPanel from "@/components/SettingsAlertsPanel.vue";
import SettingsArchivedPanel from "@/components/SettingsArchivedPanel.vue";
import SettingsBiometricsPanel from "@/components/SettingsBiometricsPanel.vue";
import SettingsCamerasPanel from "@/components/SettingsCamerasPanel.vue";
import SettingsLiveViewPanel from "@/components/SettingsLiveViewPanel.vue";
import SettingsSecurityFeedPanel from "@/components/SettingsSecurityFeedPanel.vue";
import SettingsUsersPanel from "@/components/SettingsUsersPanel.vue";
import SettingsVehiclesPanel from "@/components/SettingsVehiclesPanel.vue";
import { useTheme } from "@/composables/useTheme";
import { useAuthStore } from "@/stores/auth";

import type { LandingPage } from "@/api";

const MIN_PASSWORD_LENGTH = 12;

const auth = useAuthStore();
const toast = useToast();
const route = useRoute();
const { isDark, setDark } = useTheme();

interface SettingsSection {
  value: string;
  label: string;
  icon: string;
  adminOnly: boolean;
}

// Order is part of the settings IA: General first (every role lands here),
// admin-only configuration sections in workflow order, About last (credits/
// info, not config, open to every role like General).
const SECTIONS: SettingsSection[] = [
  { value: "general", label: "General", icon: "pi pi-user", adminOnly: false },
  { value: "users", label: "Users", icon: "pi pi-users", adminOnly: true },
  { value: "ai", label: "AI Provider", icon: "pi pi-sparkles", adminOnly: true },
  { value: "biometrics", label: "Biometrics", icon: "pi pi-id-card", adminOnly: true },
  { value: "cameras", label: "Cameras", icon: "pi pi-video", adminOnly: true },
  { value: "vehicles", label: "Vehicles", icon: "pi pi-car", adminOnly: true },
  { value: "alerts", label: "Alerts", icon: "pi pi-bell", adminOnly: true },
  { value: "live-view", label: "Live View", icon: "pi pi-eye", adminOnly: true },
  { value: "security-feed", label: "Security Feed", icon: "pi pi-th-large", adminOnly: true },
  { value: "archived", label: "Archived", icon: "pi pi-inbox", adminOnly: true },
  { value: "about", label: "About", icon: "pi pi-info-circle", adminOnly: false },
];

const visibleSections = computed(() =>
  SECTIONS.filter((section) => !section.adminOnly || auth.isAdmin),
);

const requestedTab = typeof route.query.tab === "string" ? route.query.tab : "general";
const activeTab = ref(
  visibleSections.value.some((section) => section.value === requestedTab)
    ? requestedTab
    : "general",
);

function selectSection(value: string): void {
  activeTab.value = value;
}

// WAI-ARIA tablist pattern, automatic activation: arrow keys both move focus
// and switch the active section, matching the roving tabindex below. Both
// axes are handled since the layout itself switches between a vertical
// sidebar (desktop) and a horizontal scrollable row (mobile).
function onNavKeydown(event: KeyboardEvent, currentValue: string): void {
  const sections = visibleSections.value;
  const index = sections.findIndex((section) => section.value === currentValue);
  let nextIndex: number | null = null;
  if (event.key === "ArrowDown" || event.key === "ArrowRight") {
    nextIndex = (index + 1) % sections.length;
  } else if (event.key === "ArrowUp" || event.key === "ArrowLeft") {
    nextIndex = (index - 1 + sections.length) % sections.length;
  } else if (event.key === "Home") {
    nextIndex = 0;
  } else if (event.key === "End") {
    nextIndex = sections.length - 1;
  }
  if (nextIndex === null) return;
  event.preventDefault();
  // nextIndex is always a bounded array index computed just above, never
  // external input.
  // eslint-disable-next-line security/detect-object-injection
  const nextValue = sections[nextIndex]!.value;
  activeTab.value = nextValue;
  void nextTick(() => {
    document.querySelector<HTMLElement>(`[data-testid="settings-nav-${nextValue}"]`)?.focus();
  });
}

const displayName = ref("");
const timezone = ref("UTC");
const defaultLandingPage = ref<LandingPage>("library");
const savingProfile = ref(false);

const landingPageOptions: { label: string; value: LandingPage }[] = [
  { label: "Library", value: "library" },
  { label: "Security Feed", value: "security_feed" },
];

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
    defaultLandingPage.value = auth.user.default_landing_page;
  }
});

async function saveProfile(): Promise<void> {
  savingProfile.value = true;
  try {
    auth.user = await updateMe({
      display_name: displayName.value,
      timezone: timezone.value,
      default_landing_page: defaultLandingPage.value,
    });
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

const syncIntervalSeconds = ref(60);
const initialSyncDays = ref(3);
const autoAnalyzeLimit = ref(5);
const blinkSyncIsDefault = ref(true);
const savingBlinkSync = ref(false);
const blinkSyncError = ref("");

onMounted(async () => {
  if (auth.user?.is_superuser) {
    try {
      const settings = await getBlinkSyncSettings();
      syncIntervalSeconds.value = settings.sync_interval_seconds;
      initialSyncDays.value = settings.initial_sync_days;
      autoAnalyzeLimit.value = settings.auto_analyze_limit;
      blinkSyncIsDefault.value = settings.is_default;
    } catch {
      // Non-fatal — the fields just start at their fallback values above.
    }
  }
});

async function saveBlinkSyncSettings(): Promise<void> {
  blinkSyncError.value = "";
  savingBlinkSync.value = true;
  try {
    const settings = await updateBlinkSyncSettings({
      sync_interval_seconds: syncIntervalSeconds.value,
      initial_sync_days: initialSyncDays.value,
      auto_analyze_limit: autoAnalyzeLimit.value,
    });
    syncIntervalSeconds.value = settings.sync_interval_seconds;
    initialSyncDays.value = settings.initial_sync_days;
    autoAnalyzeLimit.value = settings.auto_analyze_limit;
    blinkSyncIsDefault.value = settings.is_default;
    toast.add({ severity: "success", summary: "Blink sync settings saved", life: 2500 });
  } catch (caught) {
    blinkSyncError.value = caught instanceof ApiError ? caught.message : "Unexpected error.";
  } finally {
    savingBlinkSync.value = false;
  }
}
</script>

<template>
  <section>
    <PageHeader
      title="Settings"
      description="Your profile, security, appearance, and — for admins — Blink, AI, biometrics, cameras, vehicles, alerts, and household access."
    />

    <div class="settings-layout">
      <nav
        class="settings-nav"
        role="tablist"
        aria-orientation="vertical"
        aria-label="Settings sections"
        data-testid="settings-nav"
      >
        <button
          v-for="section in visibleSections"
          :key="section.value"
          type="button"
          role="tab"
          class="settings-nav-item"
          :class="{ active: activeTab === section.value }"
          :aria-selected="activeTab === section.value"
          :tabindex="activeTab === section.value ? 0 : -1"
          :data-testid="`settings-nav-${section.value}`"
          @click="selectSection(section.value)"
          @keydown="onNavKeydown($event, section.value)"
        >
          <i
            :class="section.icon"
            aria-hidden="true"
          />
          <span>{{ section.label }}</span>
        </button>
      </nav>

      <div
        class="settings-content"
        role="tabpanel"
      >
        <div
          v-if="activeTab === 'general'"
          class="panels"
        >
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
              <label class="field">
                <span class="field-label">Default landing page</span>
                <Select
                  v-model="defaultLandingPage"
                  :options="landingPageOptions"
                  option-label="label"
                  option-value="value"
                  fluid
                  data-testid="default-landing-page"
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

          <article
            v-if="auth.user?.is_superuser"
            class="panel"
          >
            <h3 class="panel-title">
              Blink sync
            </h3>
            <p class="panel-hint">
              How often and how far back this server syncs with your Blink account.
            </p>
            <div class="panel-body">
              <label class="field">
                <span class="field-label">Sync interval (seconds)</span>
                <InputNumber
                  v-model="syncIntervalSeconds"
                  :min="10"
                  :max="3600"
                  show-buttons
                  fluid
                  data-testid="blink-sync-interval"
                />
              </label>
              <label class="field">
                <span class="field-label">Initial sync lookback (days)</span>
                <InputNumber
                  v-model="initialSyncDays"
                  :min="1"
                  :max="30"
                  show-buttons
                  fluid
                  data-testid="blink-initial-sync-days"
                />
              </label>
              <label class="field">
                <span class="field-label">Auto-analyze limit per sync</span>
                <InputNumber
                  v-model="autoAnalyzeLimit"
                  :min="1"
                  :max="20"
                  show-buttons
                  fluid
                  data-testid="blink-auto-analyze-limit"
                />
              </label>
              <p class="muted">
                {{ blinkSyncIsDefault ? "Using the default from server configuration." : "Custom values." }}
              </p>
              <Message
                v-if="blinkSyncError"
                severity="error"
                :closable="false"
                data-testid="blink-sync-error"
              >
                {{ blinkSyncError }}
              </Message>
              <div class="panel-actions">
                <Button
                  label="Save"
                  :loading="savingBlinkSync"
                  data-testid="save-blink-sync"
                  @click="saveBlinkSyncSettings"
                />
              </div>
            </div>
          </article>
        </div>

        <SettingsUsersPanel v-else-if="activeTab === 'users' && auth.isAdmin" />
        <SettingsAiProviderPanel v-else-if="activeTab === 'ai' && auth.isAdmin" />
        <SettingsBiometricsPanel v-else-if="activeTab === 'biometrics' && auth.isAdmin" />
        <SettingsCamerasPanel v-else-if="activeTab === 'cameras' && auth.isAdmin" />
        <SettingsVehiclesPanel v-else-if="activeTab === 'vehicles' && auth.isAdmin" />
        <SettingsAlertsPanel v-else-if="activeTab === 'alerts' && auth.isAdmin" />
        <SettingsLiveViewPanel v-else-if="activeTab === 'live-view' && auth.isAdmin" />
        <SettingsSecurityFeedPanel v-else-if="activeTab === 'security-feed' && auth.isAdmin" />
        <SettingsArchivedPanel v-else-if="activeTab === 'archived' && auth.isAdmin" />
        <SettingsAboutPanel v-else />
      </div>
    </div>
  </section>
</template>

<style scoped>
.settings-layout {
  display: flex;
  align-items: flex-start;
  gap: 24px;
}

.settings-nav {
  flex-shrink: 0;
  width: 220px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  position: sticky;
  top: 0;
}

.settings-nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border: none;
  border-radius: 10px;
  background: transparent;
  color: var(--p-surface-600);
  font: inherit;
  font-size: 0.88rem;
  font-weight: 500;
  text-align: left;
  cursor: pointer;
  transition:
    background 0.15s ease,
    color 0.15s ease;
}

.blink-dark .settings-nav-item {
  color: var(--p-surface-400);
}

.settings-nav-item i {
  font-size: 0.95rem;
  width: 1.1rem;
  text-align: center;
  flex-shrink: 0;
}

.settings-nav-item:hover {
  background: var(--p-surface-100);
  color: var(--p-surface-900);
}

.blink-dark .settings-nav-item:hover {
  background: color-mix(in srgb, var(--p-surface-800) 70%, transparent);
  color: var(--p-surface-100);
}

.settings-nav-item.active {
  background: color-mix(in srgb, var(--p-primary-500) 12%, transparent);
  color: var(--p-primary-600);
  font-weight: 600;
}

.blink-dark .settings-nav-item.active {
  color: var(--p-primary-300);
}

.settings-content {
  flex: 1;
  min-width: 0;
}

@media (max-width: 768px) {
  .settings-layout {
    flex-direction: column;
    gap: 16px;
  }

  .settings-nav {
    position: static;
    width: 100%;
    flex-direction: row;
    overflow-x: auto;
    padding-bottom: 4px;
    gap: 6px;
  }

  .settings-nav-item {
    flex-shrink: 0;
    white-space: nowrap;
  }
}

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
</style>
