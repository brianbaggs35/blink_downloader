<script setup lang="ts">
defineProps<{
  icon: string;
  title: string;
  description: string;
}>();
</script>

<template>
  <div class="empty-state">
    <div class="icon-ring">
      <i
        :class="icon"
        aria-hidden="true"
      />
    </div>
    <h3 class="empty-title">
      {{ title }}
    </h3>
    <p class="empty-description">
      {{ description }}
    </p>
    <div class="empty-actions">
      <slot name="actions" />
    </div>
  </div>
</template>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: 72px 24px;
  border: 1px dashed var(--p-surface-300);
  border-radius: 16px;
  background: color-mix(in srgb, var(--p-surface-0) 55%, transparent);
}

.blink-dark .empty-state {
  border-color: var(--p-surface-700);
  background: color-mix(in srgb, var(--p-surface-900) 45%, transparent);
}

.icon-ring {
  display: grid;
  place-items: center;
  width: 64px;
  height: 64px;
  border-radius: 50%;
  background: color-mix(in srgb, var(--p-primary-500) 12%, transparent);
  margin-bottom: 18px;
}

.icon-ring i {
  font-size: 1.6rem;
  color: var(--p-primary-500);
}

.blink-dark .icon-ring i {
  color: var(--p-primary-300);
}

.empty-title {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 600;
}

.empty-description {
  margin: 8px 0 0;
  max-width: 46ch;
  font-size: 0.9rem;
  line-height: 1.55;
  color: var(--p-surface-500);
}

.blink-dark .empty-description {
  color: var(--p-surface-400);
}

.empty-actions {
  margin-top: 20px;
  display: flex;
  gap: 8px;
}

.empty-actions:empty {
  display: none;
}
</style>
