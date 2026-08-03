<script setup lang="ts">
import Button from "primevue/button";
import InputText from "primevue/inputtext";
import Message from "primevue/message";
import Password from "primevue/password";
import Select from "primevue/select";
import Skeleton from "primevue/skeleton";
import Step from "primevue/step";
import StepList from "primevue/steplist";
import StepPanel from "primevue/steppanel";
import StepPanels from "primevue/steppanels";
import Stepper from "primevue/stepper";
import Tag from "primevue/tag";
import ToggleSwitch from "primevue/toggleswitch";
import { reactive, ref } from "vue";
import { useRouter } from "vue-router";

import { ApiError, getStorageSettings, listCameras, updateCamera, updateStorageSettings } from "@/api";
import BlinkAccountPanel from "@/components/BlinkAccountPanel.vue";
import AuthLayout from "@/components/AuthLayout.vue";
import StorageDirectoryBrowserDialog from "@/components/StorageDirectoryBrowserDialog.vue";
import { cameraModelLabel } from "@/lib/cameraModels";
import { useAuthStore } from "@/stores/auth";
import { useBlinkStore } from "@/stores/blink";

import type { CameraRead } from "@/api";

const MIN_PASSWORD_LENGTH = 12;
const DISCOVERY_ATTEMPTS = 6;
const DISCOVERY_DELAY_MS = 1500;

const auth = useAuthStore();
const blink = useBlinkStore();
const router = useRouter();

const activeStep = ref("1");

// ------------------------------------------------------------- step 1

const displayName = ref("");
const email = ref("");
const password = ref("");
const confirm = ref("");
const accountError = ref("");
const creatingAccount = ref(false);

// "UTC" is a valid Intl timeZone but, oddly, isn't in the IANA-backed
// supportedValuesOf() enumeration - add it explicitly so it's selectable.
const timezones = ["UTC", ...Intl.supportedValuesOf("timeZone")];
// Pre-select the browser's own timezone rather than defaulting new accounts
// to UTC - resolvedOptions().timeZone is always a real IANA zone, but the
// membership check is cheap insurance against relying on that everywhere.
const detectedTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
const timezone = ref(timezones.includes(detectedTimezone) ? detectedTimezone : "UTC");

async function createAccount(): Promise<void> {
  accountError.value = "";
  if (password.value.length < MIN_PASSWORD_LENGTH) {
    accountError.value = `Password must be at least ${MIN_PASSWORD_LENGTH} characters.`;
    return;
  }
  if (password.value !== confirm.value) {
    accountError.value = "Passwords do not match.";
    return;
  }
  creatingAccount.value = true;
  try {
    await auth.completeSetup({
      email: email.value,
      password: password.value,
      display_name: displayName.value,
      timezone: timezone.value,
    });
    void enterStorageStep();
  } catch (caught) {
    accountError.value =
      caught instanceof ApiError
        ? caught.message
        : "Setup failed. Check that the server is reachable and try again.";
  } finally {
    creatingAccount.value = false;
  }
}

// ------------------------------------------------------------- step 2

const storageDir = ref("");
const storageBrowserOpen = ref(false);
const storageError = ref("");
const savingStorageDir = ref(false);

async function enterStorageStep(): Promise<void> {
  activeStep.value = "2";
  try {
    storageDir.value = (await getStorageSettings()).storage_dir;
  } catch (caught) {
    storageError.value =
      caught instanceof ApiError ? caught.message : "Could not load storage settings.";
  }
}

function openStorageBrowser(): void {
  storageError.value = "";
  storageBrowserOpen.value = true;
}

async function selectStorageDir(path: string): Promise<void> {
  storageError.value = "";
  savingStorageDir.value = true;
  try {
    storageDir.value = (
      await updateStorageSettings({ storage_dir: path, local_storage_quota_bytes: null })
    ).storage_dir;
  } catch (caught) {
    storageError.value =
      caught instanceof ApiError ? caught.message : "Could not update the storage folder.";
  } finally {
    savingStorageDir.value = false;
  }
}

function enterBlinkStep(): void {
  activeStep.value = "3";
}

// ------------------------------------------------------------- step 4

const cameras = ref<CameraRead[]>([]);
const discoveringCameras = ref(false);
const camerasError = ref("");
const savingCamera = reactive<Record<string, boolean>>({});
let discoveryStarted = false;

async function discoverCameras(): Promise<void> {
  camerasError.value = "";
  discoveringCameras.value = true;
  try {
    await blink.syncNow();
  } catch {
    // A failed "sync now" (e.g. rate-limited right after linking) shouldn't
    // block the review step - the periodic background sync retries this on
    // its own, so just fall through to polling for whatever's already there.
  }
  try {
    for (let attempt = 0; attempt < DISCOVERY_ATTEMPTS; attempt += 1) {
      cameras.value = await listCameras();
      if (cameras.value.length > 0) {
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, DISCOVERY_DELAY_MS));
    }
  } catch (caught) {
    camerasError.value = caught instanceof ApiError ? caught.message : "Could not load cameras.";
  } finally {
    discoveringCameras.value = false;
  }
}

function enterReviewStep(): void {
  activeStep.value = "4";
  if (!discoveryStarted && blink.isLinked) {
    discoveryStarted = true;
    void discoverCameras();
  }
}

async function toggleCamera(camera: CameraRead, value: boolean): Promise<void> {
  savingCamera[camera.id] = true;
  try {
    const updated = await updateCamera(camera.id, value, camera.security_context);
    const index = cameras.value.findIndex((c) => c.id === camera.id);
    // eslint-disable-next-line security/detect-object-injection
    cameras.value[index] = updated;
  } catch {
    // The toggle just visually reverts (model-value falls back to the
    // unchanged camera) - Settings > Cameras remains the durable place to
    // manage this if a transient error happens mid-wizard.
  } finally {
    savingCamera[camera.id] = false;
  }
}

function finish(): void {
  void router.push({ name: "library" });
}
</script>

<template>
  <AuthLayout
    heading="Welcome to Blink AI Security"
    subheading="A few quick steps to get your household set up."
    wide
  >
    <Stepper
      :value="activeStep"
      linear
    >
      <StepList>
        <Step value="1">
          Account
        </Step>
        <Step value="2">
          Storage
        </Step>
        <Step value="3">
          Blink
        </Step>
        <Step value="4">
          Review
        </Step>
      </StepList>
      <StepPanels>
        <StepPanel value="1">
          <form
            class="setup-form"
            @submit.prevent="createAccount"
          >
            <label class="field">
              <span class="field-label">Display name</span>
              <InputText
                v-model="displayName"
                autocomplete="name"
                fluid
                data-testid="display-name"
              />
            </label>
            <label class="field">
              <span class="field-label">Email</span>
              <InputText
                v-model="email"
                type="email"
                autocomplete="email"
                required
                fluid
                data-testid="email"
              />
            </label>
            <label class="field">
              <span class="field-label">Password</span>
              <Password
                v-model="password"
                toggle-mask
                required
                fluid
                data-testid="password"
              />
            </label>
            <label class="field">
              <span class="field-label">Confirm password</span>
              <Password
                v-model="confirm"
                :feedback="false"
                toggle-mask
                required
                fluid
                data-testid="confirm"
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
            <Message
              v-if="accountError"
              severity="error"
              :closable="false"
              data-testid="setup-error"
            >
              {{ accountError }}
            </Message>
            <div class="step-actions">
              <Button
                type="submit"
                label="Continue"
                :loading="creatingAccount"
                fluid
                data-testid="submit"
              />
            </div>
          </form>
        </StepPanel>

        <StepPanel value="2">
          <p class="step-intro">
            Clips download to local disk by default. Pick a different folder now if you'd like,
            or leave it as-is and change it anytime from the Storage tab.
          </p>
          <div class="storage-current">
            <i
              class="pi pi-folder"
              aria-hidden="true"
            />
            <span data-testid="setup-storage-dir">{{ storageDir }}</span>
          </div>
          <Message
            v-if="storageError"
            severity="error"
            :closable="false"
            data-testid="setup-storage-error"
          >
            {{ storageError }}
          </Message>
          <Button
            label="Browse"
            icon="pi pi-folder-open"
            severity="secondary"
            outlined
            :loading="savingStorageDir"
            data-testid="setup-storage-browse"
            @click="openStorageBrowser"
          />
          <div class="step-actions">
            <Button
              label="Continue"
              fluid
              data-testid="storage-step-continue"
              @click="enterBlinkStep"
            />
          </div>
        </StepPanel>

        <StepPanel value="3">
          <p class="step-intro">
            Link the Blink account your cameras and clips come from. You can skip this and do it
            later from Settings if you'd rather.
          </p>
          <!-- Stepper has no lazy-panel option (unlike Tabs) - every StepPanel
          mounts up front, so this must stay un-mounted until step 3 is
          actually reached. Mounted from step 1, it would call the
          authenticated getBlinkStatus() while the visitor is still
          anonymous, fail with a 401, and never retry once step 1 logs
          them in - it only fetches once, on mount. -->
          <BlinkAccountPanel v-if="activeStep === '3'" />
          <div class="step-actions">
            <Button
              v-if="blink.isLinked"
              label="Continue"
              fluid
              data-testid="blink-step-continue"
              @click="enterReviewStep"
            />
            <Button
              v-else
              label="Skip for now"
              severity="secondary"
              outlined
              fluid
              data-testid="blink-step-skip"
              @click="enterReviewStep"
            />
          </div>
        </StepPanel>

        <StepPanel value="4">
          <p class="step-intro">
            Here's what we found. You can turn off syncing and AI analysis for any camera you'd
            rather this app ignore — everything works fine with just one camera enabled.
          </p>

          <div
            v-if="!blink.isLinked"
            data-testid="review-no-blink"
          >
            <Message
              severity="info"
              :closable="false"
            >
              No Blink account linked yet — link one anytime from Settings to start syncing
              cameras and clips.
            </Message>
          </div>

          <div
            v-else-if="discoveringCameras && cameras.length === 0"
            data-testid="review-discovering"
          >
            <Skeleton
              height="72px"
              border-radius="10px"
              class="camera-skeleton"
            />
            <p class="muted">
              Discovering your cameras — this can take a few seconds…
            </p>
          </div>

          <Message
            v-else-if="camerasError"
            severity="error"
            :closable="false"
            data-testid="review-cameras-error"
          >
            {{ camerasError }}
          </Message>

          <Message
            v-else-if="cameras.length === 0"
            severity="warn"
            :closable="false"
            data-testid="review-no-cameras"
          >
            No cameras showed up yet. That's fine — sync runs in the background, and they'll
            appear in Settings → Cameras as soon as they do.
          </Message>

          <div
            v-else
            class="camera-list"
            data-testid="review-camera-list"
          >
            <article
              v-for="camera in cameras"
              :key="camera.id"
              class="camera-row"
              :data-testid="`review-camera-${camera.id}`"
            >
              <div class="camera-identity">
                <span class="camera-name">{{ camera.name }}</span>
                <Tag
                  :value="cameraModelLabel(camera.camera_type)"
                  severity="secondary"
                />
              </div>
              <div class="camera-toggle">
                <span class="muted">{{ camera.enabled ? "Enabled" : "Disabled" }}</span>
                <ToggleSwitch
                  :model-value="camera.enabled"
                  :disabled="savingCamera[camera.id]"
                  :data-testid="`review-camera-toggle-${camera.id}`"
                  @update:model-value="(v: boolean) => toggleCamera(camera, v)"
                />
              </div>
            </article>
          </div>

          <Button
            v-if="blink.isLinked"
            label="Refresh"
            icon="pi pi-refresh"
            severity="secondary"
            outlined
            size="small"
            class="refresh-button"
            :loading="discoveringCameras"
            data-testid="review-refresh"
            @click="discoverCameras"
          />

          <Message
            severity="info"
            :closable="false"
            class="ai-nudge"
          >
            One more thing: AI analysis, vehicle protection, and facial recognition are all off
            by default. Head to <RouterLink :to="{ name: 'settings', query: { tab: 'ai' } }">
              Settings → AI
            </RouterLink> to choose a provider and turn it on whenever you're ready.
          </Message>

          <div class="step-actions">
            <Button
              label="Go to Library"
              fluid
              data-testid="finish-setup"
              @click="finish"
            />
          </div>
        </StepPanel>
      </StepPanels>
    </Stepper>

    <StorageDirectoryBrowserDialog
      v-model:visible="storageBrowserOpen"
      :initial-path="storageDir"
      @select="selectStorageDir"
    />
  </AuthLayout>
</template>

<style scoped>
.setup-form {
  display: flex;
  flex-direction: column;
  gap: 18px;
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

.step-intro {
  margin: 0 0 16px;
  font-size: 0.85rem;
  line-height: 1.55;
  color: var(--p-surface-500);
}

.step-actions {
  margin-top: 20px;
}

.storage-current {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 16px;
  padding: 8px 12px;
  border-radius: 8px;
  font-size: 0.85rem;
  font-family: var(--font-mono, monospace);
  background: var(--p-surface-50);
  overflow-wrap: anywhere;
}

.blink-dark .storage-current {
  background: color-mix(in srgb, var(--p-surface-900) 70%, transparent);
}

.camera-skeleton {
  margin-bottom: 12px;
}

.muted {
  margin: 8px 0 0;
  font-size: 0.82rem;
  color: var(--p-surface-500);
}

.camera-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.camera-row {
  padding: 12px 14px;
  border-radius: 10px;
  background: var(--p-surface-50);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.blink-dark .camera-row {
  background: color-mix(in srgb, var(--p-surface-800) 55%, transparent);
}

.camera-identity {
  display: flex;
  align-items: center;
  gap: 10px;
}

.camera-name {
  font-size: 0.9rem;
  font-weight: 600;
}

.camera-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
}

.refresh-button {
  margin-top: 12px;
}

.ai-nudge {
  margin-top: 20px;
}
</style>
