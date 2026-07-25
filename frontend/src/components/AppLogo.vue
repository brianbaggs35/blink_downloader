<script setup lang="ts">
withDefaults(defineProps<{ size?: number }>(), { size: 32 });
</script>

<template>
  <span
    class="app-logo"
    role="img"
    aria-label="Blink AI Security"
  >
    <svg
      :width="size"
      :height="size"
      viewBox="0 0 32 32"
      aria-hidden="true"
    >
      <rect
        width="32"
        height="32"
        rx="8"
        class="logo-plate"
      />
      <circle
        cx="16"
        cy="16"
        r="9"
        fill="none"
        class="logo-ring"
        stroke-width="2.5"
      />
      <circle
        cx="16"
        cy="16"
        r="3.5"
        class="logo-iris"
      />
      <path
        d="M16 3.5v4M16 24.5v4M3.5 16h4M24.5 16h4"
        class="logo-ring"
        stroke-width="2"
        stroke-linecap="round"
      />
    </svg>
  </span>
</template>

<style scoped>
.app-logo {
  display: inline-flex;
  line-height: 0;
}

.logo-plate {
  fill: var(--p-surface-900);
}

.logo-ring {
  stroke: var(--p-primary-400);
}

.logo-iris {
  fill: var(--p-primary-400);
}
</style>
