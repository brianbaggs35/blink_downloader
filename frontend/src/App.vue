<script setup lang="ts">
import ConfirmDialog from "primevue/confirmdialog";
import Toast from "primevue/toast";
</script>

<template>
  <RouterView />
  <Toast position="top-right" />
  <ConfirmDialog />
</template>

<style>
/* Toast teleports to document.body, so this can't be scoped. Clear the
 * sticky topbar (z-index 10) rather than overlapping it. */
.p-toast-top-right {
  top: calc(var(--app-topbar-height) + 16px) !important;
}
</style>
