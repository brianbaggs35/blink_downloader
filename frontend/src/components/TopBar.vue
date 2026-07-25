<script setup lang="ts">
import Button from "primevue/button";
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";

import { useTheme } from "@/composables/useTheme";
import { useAuthStore } from "@/stores/auth";

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const { isDark, toggle } = useTheme();

const title = computed(() => (route.meta.title as string | undefined) ?? "");

const initials = computed(() => {
  const parts = auth.displayName.split(/[\s@.]+/).filter(Boolean);
  return parts
    .slice(0, 2)
    .map((part) => part.charAt(0))
    .join("")
    .toUpperCase();
});

async function signOut(): Promise<void> {
  await auth.logout();
  await router.push({ name: "login" });
}
</script>

<template>
  <header class="topbar">
    <h1 class="page-title">
      {{ title }}
    </h1>
    <div class="actions">
      <Button
        :icon="isDark ? 'pi pi-sun' : 'pi pi-moon'"
        severity="secondary"
        text
        rounded
        :aria-label="isDark ? 'Switch to light theme' : 'Switch to dark theme'"
        data-testid="theme-toggle"
        @click="toggle()"
      />
      <div
        class="user-chip"
        data-testid="user-chip"
      >
        <span
          class="avatar"
          aria-hidden="true"
        >{{ initials }}</span>
        <span class="user-name">{{ auth.displayName }}</span>
      </div>
      <Button
        icon="pi pi-sign-out"
        severity="secondary"
        text
        rounded
        aria-label="Sign out"
        data-testid="sign-out"
        @click="signOut"
      />
    </div>
  </header>
</template>

<style scoped>
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: var(--app-topbar-height);
  padding: 0 28px;
  border-bottom: 1px solid var(--p-surface-200);
  background: color-mix(in srgb, var(--p-surface-0) 75%, transparent);
  backdrop-filter: blur(8px);
  position: sticky;
  top: 0;
  z-index: 10;
}

.blink-dark .topbar {
  border-bottom-color: var(--p-surface-800);
  background: color-mix(in srgb, var(--p-surface-950) 75%, transparent);
}

.page-title {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 600;
  letter-spacing: 0.01em;
}

.actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.user-chip {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 12px 4px 4px;
  border-radius: 999px;
  border: 1px solid var(--p-surface-200);
}

.blink-dark .user-chip {
  border-color: var(--p-surface-700);
}

.avatar {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  background: color-mix(in srgb, var(--p-primary-500) 18%, transparent);
  color: var(--p-primary-600);
  font-size: 0.72rem;
  font-weight: 700;
}

.blink-dark .avatar {
  color: var(--p-primary-300);
}

.user-name {
  font-size: 0.85rem;
  font-weight: 500;
}
</style>
