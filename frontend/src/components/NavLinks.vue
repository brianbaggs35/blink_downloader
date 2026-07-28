<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";

import { useAuthStore } from "@/stores/auth";

interface NavItem {
  label: string;
  icon: string;
  to: { name: string };
  adminOnly?: boolean;
}

interface NavGroup {
  label: string;
  items: NavItem[];
}

// Order is part of the product spec: Security Feed, Library, Status, Live
// View, Storage, AI, AI Usage, Vehicles, Biometrics, Settings. Security
// Feed sits first - Brian asked for it "near the top" as the closest thing
// to an at-a-glance live dashboard.
const GROUPS: NavGroup[] = [
  {
    label: "Monitor",
    items: [
      { label: "Security Feed", icon: "pi pi-th-large", to: { name: "security-feed" } },
      { label: "Library", icon: "pi pi-images", to: { name: "library" } },
      { label: "Status", icon: "pi pi-wave-pulse", to: { name: "status" } },
      { label: "Live View", icon: "pi pi-video", to: { name: "live-view" } },
    ],
  },
  {
    label: "Archive",
    items: [
      { label: "Storage", icon: "pi pi-database", to: { name: "storage" } },
      // Unlike Storage (a real read-only view for any signed-in user),
      // Integrations has nothing but admin-only credentials/connection
      // state - the page itself 403s outright for a viewer, so the link
      // is hidden rather than leading somewhere that only ever errors.
      { label: "Integrations", icon: "pi pi-cloud", to: { name: "integrations" }, adminOnly: true },
    ],
  },
  {
    label: "Intelligence",
    items: [
      { label: "AI", icon: "pi pi-sparkles", to: { name: "ai" } },
      { label: "AI Usage", icon: "pi pi-chart-bar", to: { name: "ai-usage" } },
    ],
  },
  {
    label: "Protection",
    items: [
      { label: "Vehicles", icon: "pi pi-car", to: { name: "vehicles" } },
      { label: "Biometrics", icon: "pi pi-id-card", to: { name: "biometrics" } },
    ],
  },
  {
    label: "System",
    items: [{ label: "Settings", icon: "pi pi-cog", to: { name: "settings" } }],
  },
];

withDefaults(defineProps<{ collapsed?: boolean }>(), { collapsed: false });
const emit = defineEmits<{ navigate: [] }>();

const route = useRoute();
const auth = useAuthStore();

const groups = computed(() =>
  GROUPS.map((group) => ({
    ...group,
    items: group.items.filter((item) => !item.adminOnly || auth.isAdmin),
  })).filter((group) => group.items.length > 0),
);
</script>

<template>
  <nav
    class="nav"
    aria-label="Primary"
  >
    <div
      v-for="group in groups"
      :key="group.label"
      class="nav-group"
    >
      <p
        v-if="!collapsed"
        class="nav-group-label"
      >
        {{ group.label }}
      </p>
      <RouterLink
        v-for="item in group.items"
        :key="item.label"
        :to="item.to"
        class="nav-item"
        :class="{ active: route.name === item.to.name }"
        :title="collapsed ? item.label : undefined"
        @click="emit('navigate')"
      >
        <i
          :class="item.icon"
          aria-hidden="true"
        />
        <span v-show="!collapsed">{{ item.label }}</span>
      </RouterLink>
    </div>
  </nav>
</template>

<style scoped>
.nav {
  flex: 1;
  overflow-y: auto;
  padding: 8px 12px 16px;
}

.nav-group-label {
  margin: 18px 10px 6px;
  font-size: 0.66rem;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--p-surface-500);
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 9px 12px;
  margin: 2px 0;
  border-radius: 10px;
  font-size: 0.9rem;
  font-weight: 500;
  text-decoration: none;
  color: var(--p-surface-600);
  transition:
    background 0.15s ease,
    color 0.15s ease;
}

.blink-dark .nav-item {
  color: var(--p-surface-400);
}

.nav-item i {
  font-size: 1rem;
  width: 1.25rem;
  text-align: center;
}

.nav-item:hover {
  background: var(--p-surface-100);
  color: var(--p-surface-900);
}

.blink-dark .nav-item:hover {
  background: color-mix(in srgb, var(--p-surface-800) 70%, transparent);
  color: var(--p-surface-100);
}

.nav-item.active {
  background: color-mix(in srgb, var(--p-primary-500) 12%, transparent);
  color: var(--p-primary-600);
  box-shadow: inset 2px 0 0 var(--p-primary-500);
}

.blink-dark .nav-item.active {
  color: var(--p-primary-300);
}
</style>
