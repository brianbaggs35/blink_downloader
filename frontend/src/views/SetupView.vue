<script setup lang="ts">
import Button from "primevue/button";
import InputText from "primevue/inputtext";
import Message from "primevue/message";
import Password from "primevue/password";
import { ref } from "vue";
import { useRouter } from "vue-router";

import { ApiError } from "@/api";
import AuthLayout from "@/components/AuthLayout.vue";
import { useAuthStore } from "@/stores/auth";

const MIN_PASSWORD_LENGTH = 12;

const auth = useAuthStore();
const router = useRouter();

const displayName = ref("");
const email = ref("");
const password = ref("");
const confirm = ref("");
const error = ref("");
const loading = ref(false);

async function submit(): Promise<void> {
  error.value = "";
  if (password.value.length < MIN_PASSWORD_LENGTH) {
    error.value = `Password must be at least ${MIN_PASSWORD_LENGTH} characters.`;
    return;
  }
  if (password.value !== confirm.value) {
    error.value = "Passwords do not match.";
    return;
  }
  loading.value = true;
  try {
    await auth.completeSetup({
      email: email.value,
      password: password.value,
      display_name: displayName.value,
    });
    await router.push({ name: "library" });
  } catch (caught) {
    error.value =
      caught instanceof ApiError
        ? caught.message
        : "Setup failed. Check that the server is reachable and try again.";
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <AuthLayout
    heading="Create your admin account"
    subheading="First run: this account manages cameras, members, and settings."
  >
    <form
      class="setup-form"
      @submit.prevent="submit"
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
      <Message
        v-if="error"
        severity="error"
        :closable="false"
        data-testid="setup-error"
      >
        {{ error }}
      </Message>
      <Button
        type="submit"
        label="Create account"
        :loading="loading"
        fluid
        data-testid="submit"
      />
    </form>
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
</style>
