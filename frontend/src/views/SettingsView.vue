<script setup lang="ts">
import Button from "primevue/button";
import InputNumber from "primevue/inputnumber";
import InputText from "primevue/inputtext";
import Message from "primevue/message";
import Password from "primevue/password";
import Select from "primevue/select";
import SelectButton from "primevue/selectbutton";
import { useToast } from "primevue/usetoast";
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import {
  ApiError,
  getBlinkSyncSettings,
  updateBlinkSyncSettings,
  updateMe,
} from "@/api";
import BlinkAccountPanel from "@/components/BlinkAccountPanel.vue";
import PageHeader from "@/components/PageHeader.vue";
import SettingsAboutPanel from "@/components/SettingsAboutPanel.vue";
import SettingsAiProviderPanel from "@/components/SettingsAiProviderPanel.vue";
import SettingsAlertsPanel from "@/components/SettingsAlertsPanel.vue";
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

// Section navigation itself lives in NavLinks.vue's Settings accordion now -
// this just reads which one is active from the URL (?tab=x), same deep-link
// mechanism as before (e.g. SetupView.vue's "Settings -> AI" link). Falls
// back to General for an unrecognized value, or an admin-only one requested
// by a non-admin (matching NavLinks' own accordion, which never offers a
// non-admin an admin-only link in the first place).
const ADMIN_ONLY_TABS = new Set([
  "users",
  "ai",
  "biometrics",
  "cameras",
  "vehicles",
  "alerts",
  "live-view",
  "security-feed",
]);
const VALID_TABS = new Set(["general", "about", ...ADMIN_ONLY_TABS]);
const activeTab = computed(() => {
  const requested = route.query.tab;
  if (typeof requested !== "string" || !VALID_TABS.has(requested)) {
    return "general";
  }
  if (ADMIN_ONLY_TABS.has(requested) && !auth.isAdmin) {
    return "general";
  }
  return requested;
});

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
      <div class="settings-content">
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
        <SettingsAboutPanel v-else />
      </div>
    </div>
  </section>
</template>

<style scoped>
.settings-content {
  min-width: 0;
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
