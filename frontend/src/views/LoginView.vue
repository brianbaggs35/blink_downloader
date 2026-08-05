<script setup lang="ts">
import Button from "primevue/button";
import InputText from "primevue/inputtext";
import Message from "primevue/message";
import Password from "primevue/password";
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { ApiError } from "@/api";
import AuthLayout from "@/components/AuthLayout.vue";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();

const email = ref("");
const password = ref("");
const error = ref("");
const loading = ref(false);

async function submit(): Promise<void> {
  error.value = "";
  loading.value = true;
  try {
    await auth.login(email.value, password.value);
    const redirect = route.query.redirect;
    await router.push(typeof redirect === "string" ? redirect : { name: auth.landingRouteName });
  } catch (caught) {
    error.value =
      caught instanceof ApiError && caught.status === 400
        ? "Incorrect email or password."
        : "Sign-in failed. Check that the server is reachable and try again.";
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <AuthLayout
    heading="Welcome back"
    subheading="Sign in to your security console."
  >
    <form
      class="login-form"
      @submit.prevent="submit"
    >
      <label
        class="field"
        for="email"
      >
        <span class="field-label">Email</span>
        <InputText
          id="email"
          v-model="email"
          type="email"
          autocomplete="email"
          required
          fluid
          data-testid="email"
        />
      </label>
      <label
        class="field"
        for="password"
      >
        <span class="field-label">Password</span>
        <Password
          v-model="password"
          input-id="password"
          :feedback="false"
          toggle-mask
          required
          fluid
          :input-props="{ autocomplete: 'current-password' }"
          data-testid="password"
        />
      </label>
      <Message
        v-if="error"
        severity="error"
        :closable="false"
        data-testid="login-error"
      >
        {{ error }}
      </Message>
      <Button
        type="submit"
        label="Sign in"
        :loading="loading"
        fluid
        data-testid="submit"
      />
    </form>
  </AuthLayout>
</template>

<style scoped>
.login-form {
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
