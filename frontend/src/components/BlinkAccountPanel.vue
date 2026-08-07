<script setup lang="ts">
import Button from "primevue/button";
import Dialog from "primevue/dialog";
import InputText from "primevue/inputtext";
import Message from "primevue/message";
import Password from "primevue/password";
import Skeleton from "primevue/skeleton";
import Tag from "primevue/tag";
import { useToast } from "primevue/usetoast";
import { computed, onMounted, ref } from "vue";

import { ApiError } from "@/api";
import { useDeleteConfirm } from "@/composables/useDeleteConfirm";
import { useFormatting } from "@/composables/useFormatting";
import { useAuthStore } from "@/stores/auth";
import { useBlinkStore } from "@/stores/blink";

const auth = useAuthStore();
const blink = useBlinkStore();
const toast = useToast();
const { formatDateTime } = useFormatting();
const { confirmDelete } = useDeleteConfirm();

const username = ref("");
const password = ref("");
const linkError = ref("");
const linking = ref(false);

const twoFactorOpen = ref(false);
const linkSessionId = ref("");
const code = ref("");
const codeError = ref("");
const verifying = ref(false);

const syncing = ref(false);
const unlinking = ref(false);

const statusError = ref("");

async function loadStatus(): Promise<void> {
  statusError.value = "";
  try {
    await blink.refreshStatus();
  } catch {
    statusError.value = "Could not check your Blink connection status.";
  }
}

onMounted(() => {
  void loadStatus();
});

const statusSeverity = computed(() => {
  switch (blink.status?.status) {
    case "active":
      return "success";
    case "error":
      return "danger";
    default:
      return "info";
  }
});

async function submitLink(): Promise<void> {
  linkError.value = "";
  linking.value = true;
  try {
    const outcome = await blink.startLink(username.value, password.value);
    if (outcome.status === "verification_required" && outcome.link_session_id) {
      linkSessionId.value = outcome.link_session_id;
      twoFactorOpen.value = true;
    } else {
      password.value = "";
      toast.add({ severity: "success", summary: "Blink account linked", life: 3000 });
    }
  } catch (caught) {
    linkError.value = caught instanceof ApiError ? caught.message : "Could not reach the server.";
  } finally {
    linking.value = false;
  }
}

async function submitCode(): Promise<void> {
  codeError.value = "";
  verifying.value = true;
  try {
    await blink.completeLink(linkSessionId.value, code.value);
    twoFactorOpen.value = false;
    code.value = "";
    password.value = "";
    toast.add({ severity: "success", summary: "Blink account linked", life: 3000 });
  } catch (caught) {
    codeError.value = caught instanceof ApiError ? caught.message : "Could not reach the server.";
  } finally {
    verifying.value = false;
  }
}

async function syncNow(): Promise<void> {
  syncing.value = true;
  try {
    // blink.syncNow() itself waits (a few seconds, bounded) for the camera
    // count to catch up before resolving, so this button's own loading
    // state already covers that wait - see stores/blink.ts.
    await blink.syncNow();
    toast.add({ severity: "success", summary: "Sync complete", life: 2500 });
  } catch (caught) {
    toast.add({
      severity: "error",
      summary: "Could not start sync",
      detail: caught instanceof ApiError ? caught.message : "Unexpected error.",
      life: 4000,
    });
  } finally {
    syncing.value = false;
  }
}

function confirmUnlink(): void {
  confirmDelete({
    header: "Unlink Blink account?",
    message:
      "This stops syncing and removes stored cameras and clips from this app. Nothing is deleted from your Blink account itself.",
    acceptLabel: "Unlink",
    onAccept: () => void performUnlink(),
  });
}

async function performUnlink(): Promise<void> {
  unlinking.value = true;
  try {
    await blink.unlink();
    toast.add({ severity: "success", summary: "Blink account unlinked", life: 2500 });
  } catch (caught) {
    toast.add({
      severity: "error",
      summary: "Could not unlink",
      detail: caught instanceof ApiError ? caught.message : "Unexpected error.",
      life: 4000,
    });
  } finally {
    unlinking.value = false;
  }
}
</script>

<template>
  <article class="panel">
    <h3 class="panel-title">
      Blink Account
    </h3>
    <p class="panel-hint">
      Link the Blink account cameras and clips sync from.
    </p>

    <div
      v-if="blink.loading && !blink.status"
      data-testid="blink-loading"
    >
      <Skeleton
        height="80px"
        border-radius="8px"
      />
    </div>

    <div
      v-else-if="statusError"
      class="panel-body"
      data-testid="blink-status-error"
    >
      <Message
        severity="error"
        :closable="false"
      >
        {{ statusError }}
      </Message>
      <div class="panel-actions">
        <Button
          label="Retry"
          severity="secondary"
          outlined
          data-testid="retry-status"
          @click="loadStatus"
        />
      </div>
    </div>

    <div
      v-else-if="blink.isLinked"
      class="panel-body"
      data-testid="blink-linked"
    >
      <div class="status-row">
        <Tag
          :value="blink.status?.status === 'active' ? 'Connected' : 'Needs attention'"
          :severity="statusSeverity"
        />
        <span class="muted">{{ blink.status?.camera_count }} camera(s)</span>
      </div>
      <p
        v-if="blink.status?.last_sync"
        class="muted"
      >
        Last synced {{ formatDateTime(blink.status.last_sync) }}
      </p>
      <Message
        v-if="blink.status?.last_error"
        severity="error"
        :closable="false"
      >
        {{ blink.status.last_error }}
      </Message>
      <div
        v-if="auth.isAdmin"
        class="panel-actions"
      >
        <Button
          label="Sync now"
          icon="pi pi-refresh"
          severity="secondary"
          outlined
          :loading="syncing"
          data-testid="sync-now"
          @click="syncNow"
        />
        <Button
          label="Unlink"
          icon="pi pi-unlink"
          severity="danger"
          text
          :loading="unlinking"
          data-testid="open-unlink-confirm"
          @click="confirmUnlink"
        />
      </div>
    </div>

    <p
      v-else-if="!auth.isAdmin"
      class="muted"
      data-testid="blink-link-admin-only"
    >
      No Blink account linked yet. Ask an admin to connect one in Settings.
    </p>

    <form
      v-else
      class="panel-body"
      data-testid="blink-link-form"
      @submit.prevent="submitLink"
    >
      <label
        class="field"
        for="blink-username"
      >
        <span class="field-label">Blink email</span>
        <InputText
          id="blink-username"
          v-model="username"
          type="email"
          autocomplete="username"
          fluid
          required
          data-testid="blink-username"
        />
      </label>
      <label
        class="field"
        for="blink-password"
      >
        <span class="field-label">Blink password</span>
        <Password
          v-model="password"
          input-id="blink-password"
          :feedback="false"
          toggle-mask
          fluid
          required
          :input-props="{ autocomplete: 'current-password' }"
          data-testid="blink-password"
        />
      </label>
      <Message
        v-if="linkError"
        severity="error"
        :closable="false"
        data-testid="link-error"
      >
        {{ linkError }}
      </Message>
      <div class="panel-actions">
        <Button
          type="submit"
          label="Sign in"
          :loading="linking"
          data-testid="blink-sign-in"
        />
      </div>
    </form>

    <Dialog
      v-model:visible="twoFactorOpen"
      header="Enter your verification code"
      modal
      :style="{ width: '28rem' }"
      :breakpoints="{ '640px': '92vw' }"
      data-testid="twofa-modal"
    >
      <p class="muted">
        Blink sent a verification code to confirm this sign-in.
      </p>
      <form
        class="panel-body"
        @submit.prevent="submitCode"
      >
        <label
          class="field"
          for="twofa-code"
        >
          <span class="field-label">Verification code</span>
          <!-- kebab-case tag: SonarQube's autocomplete check only recognizes native
          input/select/textarea tags and skips hyphenated custom-element tags; PascalCase
          component tags are treated as plain unknown elements and fail Web:S6840 -->
          <input-text
            id="twofa-code"
            v-model="code"
            inputmode="numeric"
            autocomplete="one-time-code"
            fluid
            autofocus
            data-testid="twofa-code"
          />
        </label>
        <Message
          v-if="codeError"
          severity="error"
          :closable="false"
          data-testid="twofa-error"
        >
          {{ codeError }}
        </Message>
        <div class="panel-actions">
          <Button
            type="submit"
            label="Submit"
            :loading="verifying"
            fluid
            data-testid="twofa-submit"
          />
        </div>
      </form>
    </Dialog>
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

.panel-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}

.status-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.muted {
  margin: 0;
  font-size: 0.85rem;
  color: var(--p-surface-500);
}
</style>
