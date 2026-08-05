<script setup lang="ts">
import Button from "primevue/button";
import Checkbox from "primevue/checkbox";
import DatePicker from "primevue/datepicker";
import InputNumber from "primevue/inputnumber";
import InputText from "primevue/inputtext";
import Message from "primevue/message";
import Password from "primevue/password";
import Skeleton from "primevue/skeleton";
import Textarea from "primevue/textarea";
import ToggleSwitch from "primevue/toggleswitch";
import { useToast } from "primevue/usetoast";
import { computed, onMounted, ref } from "vue";

import { ApiError, getAlertSettings, testAlertChannels, updateAlertSettings } from "@/api";

import type { AlertTestResponse } from "@/api";

const toast = useToast();

const loading = ref(true);
const loadError = ref("");
const saving = ref(false);
const saveError = ref("");

const discordEnabled = ref(false);
const discordWebhookInput = ref("");
const discordClearWebhook = ref(false);
const discordWebhookSet = ref(false);

const slackEnabled = ref(false);
const slackWebhookInput = ref("");
const slackClearWebhook = ref(false);
const slackWebhookSet = ref(false);

const smtpEnabled = ref(false);
const smtpHost = ref("");
const smtpPort = ref(587);
const smtpUsername = ref("");
const smtpPasswordInput = ref("");
const smtpClearPassword = ref(false);
const smtpPasswordSet = ref(false);
const smtpUseTls = ref(true);
const smtpFromAddress = ref("");
const smtpToAddressesText = ref("");

const alertOnSuspiciousClip = ref(true);
const suspicionAlertThreshold = ref(0.5);
const alertOnVehicleProximity = ref(true);
const alertOnLowBattery = ref(true);
// DatePicker's own clear icon emits null (not "") - both mean "unset" to save().
const quietHoursStart = ref<string | null>("");
const quietHoursEnd = ref<string | null>("");

/** DatePicker's own types claim modelValue is always a Date, but
 * update-model-type="string" (paired with time-only) makes it a plain
 * "HH:MM" string at runtime - PrimeVue's .d.ts doesn't account for that
 * prop's effect on modelValue's type. Bridges the two so the template stays
 * honestly typed as string | null throughout the rest of this file. */
function timeOnlyModel(source: { value: string | null }) {
  return computed({
    get: () => source.value as unknown as Date,
    set: (value: unknown) => {
      source.value = value as string | null;
    },
  });
}

const quietHoursStartModel = timeOnlyModel(quietHoursStart);
const quietHoursEndModel = timeOnlyModel(quietHoursEnd);
const dedupWindowMinutes = ref(15);

async function load(): Promise<void> {
  loading.value = true;
  loadError.value = "";
  try {
    const s = await getAlertSettings();
    discordEnabled.value = s.discord_enabled;
    discordWebhookSet.value = s.discord_webhook_set;
    slackEnabled.value = s.slack_enabled;
    slackWebhookSet.value = s.slack_webhook_set;
    smtpEnabled.value = s.smtp_enabled;
    smtpHost.value = s.smtp_host ?? "";
    smtpPort.value = s.smtp_port;
    smtpUsername.value = s.smtp_username ?? "";
    smtpPasswordSet.value = s.smtp_password_set;
    smtpUseTls.value = s.smtp_use_tls;
    smtpFromAddress.value = s.smtp_from_address ?? "";
    smtpToAddressesText.value = s.smtp_to_addresses.join(", ");
    alertOnSuspiciousClip.value = s.alert_on_suspicious_clip;
    suspicionAlertThreshold.value = s.suspicion_alert_threshold;
    alertOnVehicleProximity.value = s.alert_on_vehicle_proximity;
    alertOnLowBattery.value = s.alert_on_low_battery;
    quietHoursStart.value = s.quiet_hours_start ? s.quiet_hours_start.slice(0, 5) : "";
    quietHoursEnd.value = s.quiet_hours_end ? s.quiet_hours_end.slice(0, 5) : "";
    dedupWindowMinutes.value = s.dedup_window_minutes;
  } catch (caught) {
    loadError.value = caught instanceof ApiError ? caught.message : "Could not load alert settings.";
  } finally {
    loading.value = false;
  }
}

onMounted(load);

function resolvedSecret(input: string, clear: boolean): string | null {
  if (input) {
    return input;
  }
  return clear ? "" : null;
}

async function save(): Promise<void> {
  saveError.value = "";
  saving.value = true;
  try {
    const toAddresses = smtpToAddressesText.value
      .split(",")
      .map((a) => a.trim())
      .filter((a) => a.length > 0);
    const settings = await updateAlertSettings({
      discord_enabled: discordEnabled.value,
      discord_webhook_url: resolvedSecret(discordWebhookInput.value, discordClearWebhook.value),
      slack_enabled: slackEnabled.value,
      slack_webhook_url: resolvedSecret(slackWebhookInput.value, slackClearWebhook.value),
      smtp_enabled: smtpEnabled.value,
      smtp_host: smtpHost.value || null,
      smtp_port: smtpPort.value,
      smtp_username: smtpUsername.value || null,
      smtp_password: resolvedSecret(smtpPasswordInput.value, smtpClearPassword.value),
      smtp_use_tls: smtpUseTls.value,
      smtp_from_address: smtpFromAddress.value || null,
      smtp_to_addresses: toAddresses,
      alert_on_suspicious_clip: alertOnSuspiciousClip.value,
      suspicion_alert_threshold: suspicionAlertThreshold.value,
      alert_on_vehicle_proximity: alertOnVehicleProximity.value,
      alert_on_low_battery: alertOnLowBattery.value,
      quiet_hours_start: quietHoursStart.value || null,
      quiet_hours_end: quietHoursEnd.value || null,
      dedup_window_minutes: dedupWindowMinutes.value,
    });
    discordWebhookSet.value = settings.discord_webhook_set;
    discordWebhookInput.value = "";
    discordClearWebhook.value = false;
    slackWebhookSet.value = settings.slack_webhook_set;
    slackWebhookInput.value = "";
    slackClearWebhook.value = false;
    smtpPasswordSet.value = settings.smtp_password_set;
    smtpPasswordInput.value = "";
    smtpClearPassword.value = false;
    toast.add({ severity: "success", summary: "Alert settings saved", life: 2500 });
  } catch (caught) {
    saveError.value = caught instanceof ApiError ? caught.message : "Unexpected error.";
  } finally {
    saving.value = false;
  }
}

const testing = ref(false);
const testResult = ref<AlertTestResponse | null>(null);
const testResultRows = computed(() => {
  if (!testResult.value) {
    return [];
  }
  const rows: { channel: string; ok: boolean; detail: string }[] = [];
  if (testResult.value.discord) {
    rows.push({ channel: "Discord", ...testResult.value.discord });
  }
  if (testResult.value.slack) {
    rows.push({ channel: "Slack", ...testResult.value.slack });
  }
  if (testResult.value.smtp) {
    rows.push({ channel: "Email", ...testResult.value.smtp });
  }
  return rows;
});

async function runTest(): Promise<void> {
  testing.value = true;
  testResult.value = null;
  try {
    testResult.value = await testAlertChannels();
  } catch (caught) {
    toast.add({
      severity: "error",
      summary: "Could not send test alert",
      detail: caught instanceof ApiError ? caught.message : "Unexpected error.",
      life: 4000,
    });
  } finally {
    testing.value = false;
  }
}

const discordPlaceholder = computed(() =>
  discordWebhookSet.value ? "•••••••••••• (saved — leave blank to keep)" : "https://discord.com/api/webhooks/…",
);
const slackPlaceholder = computed(() =>
  slackWebhookSet.value ? "•••••••••••• (saved — leave blank to keep)" : "https://hooks.slack.com/services/…",
);
const smtpPasswordPlaceholder = computed(() =>
  smtpPasswordSet.value ? "•••••••••••• (saved — leave blank to keep)" : "Not set",
);
</script>

<template>
  <article class="panel">
    <h3 class="panel-title">
      Alerts
    </h3>
    <p class="panel-hint">
      Get notified the moment something needs your attention — a clip flagged suspicious, or
      someone getting close to your vehicle.
    </p>

    <div
      v-if="loading"
      data-testid="alerts-loading"
    >
      <Skeleton
        height="280px"
        border-radius="12px"
      />
    </div>

    <Message
      v-else-if="loadError"
      severity="error"
      :closable="false"
      data-testid="alerts-load-error"
    >
      {{ loadError }}
    </Message>

    <form
      v-else
      class="panel-body"
      data-testid="alerts-form"
      @submit.prevent="save"
    >
      <section class="channel">
        <div class="toggle-row">
          <ToggleSwitch
            v-model="discordEnabled"
            data-testid="discord-enabled"
          />
          <p class="toggle-label">
            Discord
          </p>
        </div>
        <template v-if="discordEnabled">
          <label class="field">
            <span class="field-label">Webhook URL</span>
            <Password
              v-model="discordWebhookInput"
              :feedback="false"
              toggle-mask
              fluid
              :placeholder="discordPlaceholder"
              data-testid="discord-webhook"
            />
          </label>
          <label
            v-if="discordWebhookSet"
            class="clear-key"
          >
            <Checkbox
              v-model="discordClearWebhook"
              binary
              data-testid="discord-clear-webhook"
            />
            Remove the saved webhook on next save
          </label>
        </template>
      </section>

      <section class="channel">
        <div class="toggle-row">
          <ToggleSwitch
            v-model="slackEnabled"
            data-testid="slack-enabled"
          />
          <p class="toggle-label">
            Slack
          </p>
        </div>
        <template v-if="slackEnabled">
          <label class="field">
            <span class="field-label">Webhook URL</span>
            <Password
              v-model="slackWebhookInput"
              :feedback="false"
              toggle-mask
              fluid
              :placeholder="slackPlaceholder"
              data-testid="slack-webhook"
            />
          </label>
          <label
            v-if="slackWebhookSet"
            class="clear-key"
          >
            <Checkbox
              v-model="slackClearWebhook"
              binary
              data-testid="slack-clear-webhook"
            />
            Remove the saved webhook on next save
          </label>
        </template>
      </section>

      <section class="channel">
        <div class="toggle-row">
          <ToggleSwitch
            v-model="smtpEnabled"
            data-testid="smtp-enabled"
          />
          <p class="toggle-label">
            Email (SMTP)
          </p>
        </div>
        <template v-if="smtpEnabled">
          <div class="tier-grid">
            <label class="field">
              <span class="field-label">SMTP host</span>
              <InputText
                v-model="smtpHost"
                placeholder="smtp.example.com"
                fluid
                data-testid="smtp-host"
              />
            </label>
            <label class="field">
              <span class="field-label">Port</span>
              <InputNumber
                v-model="smtpPort"
                :min="1"
                :max="65535"
                :use-grouping="false"
                fluid
                data-testid="smtp-port"
              />
            </label>
            <label class="field">
              <span class="field-label">Username</span>
              <InputText
                v-model="smtpUsername"
                fluid
                data-testid="smtp-username"
              />
            </label>
            <label class="field">
              <span class="field-label">Password</span>
              <Password
                v-model="smtpPasswordInput"
                :feedback="false"
                toggle-mask
                fluid
                :placeholder="smtpPasswordPlaceholder"
                data-testid="smtp-password"
              />
            </label>
            <label class="field">
              <span class="field-label">From address</span>
              <InputText
                v-model="smtpFromAddress"
                type="email"
                placeholder="alerts@example.com"
                fluid
                data-testid="smtp-from-address"
              />
            </label>
            <div class="toggle-row inline">
              <ToggleSwitch
                v-model="smtpUseTls"
                data-testid="smtp-use-tls"
              />
              <span class="muted">Use STARTTLS</span>
            </div>
          </div>
          <label class="field">
            <span class="field-label">Send to (comma-separated)</span>
            <Textarea
              v-model="smtpToAddressesText"
              rows="2"
              auto-resize
              placeholder="you@example.com, partner@example.com"
              fluid
              data-testid="smtp-to-addresses"
            />
          </label>
          <label
            v-if="smtpPasswordSet"
            class="clear-key"
          >
            <Checkbox
              v-model="smtpClearPassword"
              binary
              data-testid="smtp-clear-password"
            />
            Remove the saved password on next save
          </label>
        </template>
      </section>

      <section class="channel">
        <h4 class="tier-title">
          When to alert
        </h4>
        <div class="toggle-row inline">
          <ToggleSwitch
            v-model="alertOnSuspiciousClip"
            data-testid="alert-on-suspicious"
          />
          <span class="muted">A clip is scored suspicious</span>
        </div>
        <label
          v-if="alertOnSuspiciousClip"
          class="field threshold-field"
        >
          <span class="field-label">Suspicion score threshold</span>
          <InputNumber
            v-model="suspicionAlertThreshold"
            :min="0"
            :max="1"
            :step="0.05"
            :min-fraction-digits="2"
            show-buttons
            data-testid="suspicion-alert-threshold"
          />
        </label>
        <div class="toggle-row inline">
          <ToggleSwitch
            v-model="alertOnVehicleProximity"
            data-testid="alert-on-proximity"
          />
          <span class="muted">Someone gets close to a protected vehicle</span>
        </div>
        <div class="toggle-row inline">
          <ToggleSwitch
            v-model="alertOnLowBattery"
            data-testid="alert-on-low-battery"
          />
          <span class="muted">A camera's battery drops to low</span>
        </div>
      </section>

      <section class="channel">
        <h4 class="tier-title">
          Quiet hours &amp; deduplication
        </h4>
        <div class="tier-grid">
          <label class="field">
            <span class="field-label">Quiet hours start</span>
            <DatePicker
              v-model="quietHoursStartModel"
              time-only
              hour-format="24"
              update-model-type="string"
              show-clear
              fluid
              data-testid="quiet-hours-start"
            />
          </label>
          <label class="field">
            <span class="field-label">Quiet hours end</span>
            <DatePicker
              v-model="quietHoursEndModel"
              time-only
              hour-format="24"
              update-model-type="string"
              show-clear
              fluid
              data-testid="quiet-hours-end"
            />
          </label>
          <label class="field">
            <span class="field-label">Don't repeat the same alert for (minutes)</span>
            <InputNumber
              v-model="dedupWindowMinutes"
              :min="0"
              :max="1440"
              fluid
              data-testid="dedup-window"
            />
          </label>
        </div>
        <p class="muted">
          Leave quiet hours blank to disable them. During quiet hours, alerts are silently
          skipped rather than queued.
        </p>
      </section>

      <Message
        v-if="saveError"
        severity="error"
        :closable="false"
        data-testid="alerts-save-error"
      >
        {{ saveError }}
      </Message>
      <div class="panel-actions">
        <Button
          type="button"
          label="Send test alert"
          severity="secondary"
          outlined
          :loading="testing"
          data-testid="test-alerts"
          @click="runTest"
        />
        <Button
          type="submit"
          label="Save alert settings"
          :loading="saving"
          data-testid="save-alerts"
        />
      </div>

      <div
        v-if="testResultRows.length > 0"
        class="test-results"
        data-testid="test-results"
      >
        <div
          v-for="row in testResultRows"
          :key="row.channel"
          :class="['test-result', row.ok ? 'ok' : 'fail']"
        >
          <i :class="row.ok ? 'pi pi-check-circle' : 'pi pi-times-circle'" />
          <strong>{{ row.channel }}:</strong> {{ row.detail }}
        </div>
      </div>
    </form>
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
  gap: 20px;
}

.channel {
  padding-top: 16px;
  border-top: 1px solid var(--p-surface-200);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.blink-dark .channel {
  border-color: var(--p-surface-800);
}

.tier-title {
  margin: 0;
  font-size: 0.88rem;
  font-weight: 700;
}

.toggle-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.toggle-row.inline {
  gap: 10px;
}

.toggle-label {
  margin: 0;
  font-size: 0.9rem;
  font-weight: 600;
}

.tier-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 14px;
  align-items: end;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.threshold-field {
  max-width: 220px;
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
  font-size: 0.82rem;
  color: var(--p-surface-600);
}

.blink-dark .clear-key {
  color: var(--p-surface-300);
}

.muted {
  font-size: 0.82rem;
  color: var(--p-surface-500);
  margin: 0;
}

.panel-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}

.test-results {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px 14px;
  border-radius: 10px;
  background: var(--p-surface-50);
}

.blink-dark .test-results {
  background: color-mix(in srgb, var(--p-surface-800) 55%, transparent);
}

.test-result {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.85rem;
}

.test-result.ok {
  color: var(--p-green-600);
}

.test-result.fail {
  color: var(--p-red-500);
}
</style>
