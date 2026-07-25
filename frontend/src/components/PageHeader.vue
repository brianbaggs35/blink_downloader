<script setup lang="ts">
defineProps<{
  title: string;
  description?: string;
}>();
</script>

<template>
  <div class="page-header">
    <div>
      <h1 class="title">
        {{ title }}
      </h1>
      <p
        v-if="description"
        class="description"
      >
        {{ description }}
      </p>
    </div>
    <div class="header-actions">
      <slot name="actions" />
    </div>
  </div>
</template>

<style scoped>
.page-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 24px;
}

.title {
  margin: 0;
  font-size: 1.45rem;
  font-weight: 700;
  letter-spacing: -0.01em;
}

.description {
  margin: 6px 0 0;
  font-size: 0.9rem;
  color: var(--p-surface-500);
  max-width: 60ch;
}

.blink-dark .description {
  color: var(--p-surface-400);
}

.header-actions {
  display: flex;
  gap: 8px;
}
</style>
