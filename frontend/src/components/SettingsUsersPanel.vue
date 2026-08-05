<script setup lang="ts">
import Button from "primevue/button";
import Dialog from "primevue/dialog";
import InputText from "primevue/inputtext";
import Message from "primevue/message";
import Password from "primevue/password";
import SelectButton from "primevue/selectbutton";
import Skeleton from "primevue/skeleton";
import Tag from "primevue/tag";
import { useToast } from "primevue/usetoast";
import { onMounted, ref } from "vue";

import { ApiError, createUser, listUsers } from "@/api";
import { useAuthStore } from "@/stores/auth";

import type { UserRead } from "@/api";

const MIN_PASSWORD_LENGTH = 12;

const roleOptions = [
  { label: "Admin", value: true },
  { label: "Viewer", value: false },
];

const auth = useAuthStore();
const toast = useToast();

const users = ref<UserRead[]>([]);
const loading = ref(true);
const loadError = ref("");

async function load(): Promise<void> {
  loading.value = true;
  loadError.value = "";
  try {
    users.value = await listUsers();
  } catch (caught) {
    loadError.value = caught instanceof ApiError ? caught.message : "Could not load users.";
  } finally {
    loading.value = false;
  }
}

onMounted(load);

const inviteOpen = ref(false);
const inviteEmail = ref("");
const inviteDisplayName = ref("");
const invitePassword = ref("");
const inviteIsSuperuser = ref(false);
const inviteError = ref("");
const inviting = ref(false);

function openInvite(): void {
  inviteEmail.value = "";
  inviteDisplayName.value = "";
  invitePassword.value = "";
  inviteIsSuperuser.value = false;
  inviteError.value = "";
  inviteOpen.value = true;
}

async function submitInvite(): Promise<void> {
  inviteError.value = "";
  if (invitePassword.value.length < MIN_PASSWORD_LENGTH) {
    inviteError.value = `Password must be at least ${MIN_PASSWORD_LENGTH} characters.`;
    return;
  }
  inviting.value = true;
  try {
    const created = await createUser({
      email: inviteEmail.value,
      password: invitePassword.value,
      display_name: inviteDisplayName.value,
      is_superuser: inviteIsSuperuser.value,
      is_active: true,
      is_verified: true,
      timezone: "UTC",
    });
    users.value = [...users.value, created];
    inviteOpen.value = false;
    toast.add({ severity: "success", summary: "User invited", life: 2500 });
  } catch (caught) {
    inviteError.value = caught instanceof ApiError ? caught.message : "Unexpected error.";
  } finally {
    inviting.value = false;
  }
}
</script>

<template>
  <article class="panel">
    <div class="panel-heading">
      <div>
        <h3 class="panel-title">
          Users
        </h3>
        <p class="panel-hint">
          Everyone with access to this household's cameras and clips.
        </p>
      </div>
      <Button
        label="Invite user"
        icon="pi pi-user-plus"
        size="small"
        data-testid="open-invite"
        @click="openInvite"
      />
    </div>

    <div
      v-if="loading"
      class="panel-body"
      data-testid="users-loading"
    >
      <Skeleton
        v-for="n in 3"
        :key="n"
        height="52px"
        border-radius="10px"
      />
    </div>

    <Message
      v-else-if="loadError"
      severity="error"
      :closable="false"
      data-testid="users-load-error"
    >
      {{ loadError }}
    </Message>

    <ul
      v-else
      class="user-list"
      data-testid="user-list"
    >
      <li
        v-for="user in users"
        :key="user.id"
        class="user-row"
        :data-testid="`user-row-${user.id}`"
      >
        <div class="user-identity">
          <span class="user-name">{{ user.display_name || user.email }}</span>
          <span class="user-email">{{ user.email }}</span>
        </div>
        <div class="user-tags">
          <Tag
            :value="user.is_superuser ? 'Admin' : 'Viewer'"
            :severity="user.is_superuser ? 'warn' : 'info'"
          />
          <Tag
            v-if="!user.is_active"
            value="Disabled"
            severity="danger"
          />
          <Tag
            v-if="user.id === auth.user?.id"
            value="You"
            severity="secondary"
          />
        </div>
      </li>
    </ul>

    <Dialog
      v-model:visible="inviteOpen"
      header="Invite a user"
      modal
      :style="{ width: '28rem' }"
      :breakpoints="{ '640px': '92vw' }"
      data-testid="invite-modal"
    >
      <form
        class="panel-body"
        data-testid="invite-form"
        @submit.prevent="submitInvite"
      >
        <label
          class="field"
          for="invite-email"
        >
          <span class="field-label">Email</span>
          <InputText
            id="invite-email"
            v-model="inviteEmail"
            type="email"
            fluid
            required
            data-testid="invite-email"
          />
        </label>
        <label
          class="field"
          for="invite-display-name"
        >
          <span class="field-label">Display name</span>
          <InputText
            id="invite-display-name"
            v-model="inviteDisplayName"
            fluid
            data-testid="invite-display-name"
          />
        </label>
        <label
          class="field"
          for="invite-password"
        >
          <span class="field-label">Temporary password</span>
          <Password
            v-model="invitePassword"
            input-id="invite-password"
            toggle-mask
            fluid
            required
            data-testid="invite-password"
          />
        </label>
        <div class="field">
          <span
            id="invite-role-label"
            class="field-label"
          >Role</span>
          <SelectButton
            v-model="inviteIsSuperuser"
            :options="roleOptions"
            option-label="label"
            option-value="value"
            :allow-empty="false"
            aria-labelledby="invite-role-label"
            data-testid="invite-role"
          />
        </div>
        <Message
          v-if="inviteError"
          severity="error"
          :closable="false"
          data-testid="invite-error"
        >
          {{ inviteError }}
        </Message>
        <div class="panel-actions">
          <Button
            type="submit"
            label="Send invite"
            :loading="inviting"
            data-testid="submit-invite"
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

.panel-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.panel-title {
  margin: 0;
  font-size: 1rem;
  font-weight: 700;
}

.panel-hint {
  margin: 4px 0 0;
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
}

.user-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.user-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  border-radius: 10px;
  background: var(--p-surface-50);
  flex-wrap: wrap;
}

.blink-dark .user-row {
  background: color-mix(in srgb, var(--p-surface-800) 55%, transparent);
}

.user-identity {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.user-name {
  font-size: 0.9rem;
  font-weight: 600;
}

.user-email {
  font-size: 0.78rem;
  color: var(--p-surface-500);
}

.user-tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
</style>
