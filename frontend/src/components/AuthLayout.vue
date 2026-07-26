<script setup lang="ts">
import AppLogo from "./AppLogo.vue";

withDefaults(
  defineProps<{
    heading: string;
    subheading: string;
    wide?: boolean;
  }>(),
  { wide: false },
);
</script>

<template>
  <div class="auth-screen">
    <div :class="['auth-card', { 'auth-card-wide': wide }]">
      <div class="auth-brand">
        <AppLogo :size="44" />
        <span class="auth-product">Blink AI Security</span>
      </div>
      <h1 class="auth-heading">
        {{ heading }}
      </h1>
      <p class="auth-subheading">
        {{ subheading }}
      </p>
      <slot />
    </div>
  </div>
</template>

<style scoped>
.auth-screen {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 24px;
  background:
    radial-gradient(
      900px 500px at 50% -10%,
      color-mix(in srgb, var(--p-primary-600) 16%, transparent),
      transparent 70%
    ),
    linear-gradient(color-mix(in srgb, var(--p-surface-500) 5%, transparent) 1px, transparent 1px),
    linear-gradient(
      90deg,
      color-mix(in srgb, var(--p-surface-500) 5%, transparent) 1px,
      transparent 1px
    );
  background-size:
    100% 100%,
    36px 36px,
    36px 36px;
}

.auth-card {
  width: 100%;
  max-width: 420px;
  padding: 40px 36px;
  border-radius: 20px;
  border: 1px solid var(--p-surface-200);
  background: var(--p-surface-0);
  box-shadow: 0 24px 60px -24px rgb(0 0 0 / 0.35);
}

.auth-card-wide {
  max-width: 640px;
}

.blink-dark .auth-card {
  border-color: var(--p-surface-800);
  background: color-mix(in srgb, var(--p-surface-900) 80%, var(--p-surface-950));
}

.auth-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 28px;
}

.auth-product {
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--p-primary-500);
}

.auth-heading {
  margin: 0;
  font-size: 1.45rem;
  font-weight: 700;
  letter-spacing: -0.01em;
}

.auth-subheading {
  margin: 8px 0 26px;
  font-size: 0.9rem;
  line-height: 1.5;
  color: var(--p-surface-500);
}

.blink-dark .auth-subheading {
  color: var(--p-surface-400);
}
</style>
