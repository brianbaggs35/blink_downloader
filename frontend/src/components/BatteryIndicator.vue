<script setup lang="ts">
import { Icon, addIcon } from "@iconify/vue";
import Tag from "primevue/tag";
import { computed } from "vue";

import { BATTERY_STATUS_META, batteryStatus } from "@/lib/battery";

// Registered once, at module scope, from data pulled directly from the mdi
// (Material Design Icons) Iconify collection - never fetched from Iconify's
// public API at runtime (this app is self-hosted and shouldn't depend on an
// external service just to render an icon). @iconify/vue's <Icon> component
// only calls out to the API as a fallback for icon names it doesn't already
// have registered, so these three names never trigger that path.
addIcon("mdi:battery", {
  body: '<path fill="currentColor" d="M16.67 4H15V2H9v2H7.33A1.33 1.33 0 0 0 6 5.33v15.34C6 21.4 6.6 22 7.33 22h9.34A1.33 1.33 0 0 0 18 20.67V5.33C18 4.6 17.4 4 16.67 4"/>',
  width: 24,
  height: 24,
});
addIcon("mdi:battery-alert", {
  body: '<path fill="currentColor" d="M13 14h-2V8h2m0 10h-2v-2h2m3.7-12H15V2H9v2H7.3C6.6 4 6 4.6 6 5.3v15.3c0 .8.6 1.4 1.3 1.4h9.3c.7 0 1.3-.6 1.3-1.3V5.3c.1-.7-.5-1.3-1.2-1.3"/>',
  width: 24,
  height: 24,
});
addIcon("mdi:battery-unknown", {
  body: '<path fill="currentColor" d="m15.07 12.25l-.9.92c-.54.54-.92 1.01-1.08 1.83h-2.04c.11-.9.51-1.72 1.12-2.33l1.24-1.26c.37-.36.59-.86.59-1.41a2 2 0 0 0-2-2a2 2 0 0 0-2 2H8a4 4 0 0 1 4-4a4 4 0 0 1 4 4c0 .88-.36 1.68-.93 2.25M13 19h-2v-2h2m3.67-13H15V2H9v2H7.33A1.33 1.33 0 0 0 6 5.33v15.33C6 21.4 6.6 22 7.33 22h9.34c.73 0 1.33-.6 1.33-1.34V5.33C18 4.59 17.4 4 16.67 4"/>',
  width: 24,
  height: 24,
});

const props = defineProps<{
  /** Raw battery_state string from Blink ("ok"/"low"/etc), matched
   * case-insensitively - blinkpy passes Blink's cloud value through
   * unnormalized. null/undefined or any unrecognized value renders as
   * "unknown" rather than guessing. */
  battery: string | null | undefined;
}>();

const status = computed(() => batteryStatus(props.battery));
const meta = computed(() => BATTERY_STATUS_META[status.value]);
</script>

<template>
  <Tag
    :value="meta.label"
    :severity="meta.severity"
    :class="`battery-indicator battery-indicator--${status}`"
  >
    <template #icon>
      <Icon :icon="meta.icon" />
    </template>
  </Tag>
</template>

<style scoped>
.battery-indicator :deep(svg) {
  width: 1em;
  height: 1em;
}
</style>
