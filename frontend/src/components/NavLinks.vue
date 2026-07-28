<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

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

interface SettingsSection {
  value: string;
  label: string;
  icon: string;
  adminOnly?: boolean;
}

// Order is part of the product spec: Security Feed, Library, Status, Live
// View, Storage, Connect, AI, AI Usage, Vehicles, Biometrics, Settings.
// Security Feed sits first - Brian asked for it "near the top" as the
// closest thing to an at-a-glance live dashboard. Integrations lives in its
// own group (not nested under Archive/Storage) since future integrations
// may have nothing to do with storage.
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
    items: [{ label: "Storage", icon: "pi pi-database", to: { name: "storage" } }],
  },
  {
    label: "Integrations",
    items: [
      // Nothing on this page but admin-only credentials/connection state -
      // it 403s outright for a viewer, so the link is hidden rather than
      // leading somewhere that only ever errors.
      { label: "Connect", icon: "pi pi-cloud", to: { name: "integrations" }, adminOnly: true },
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
];

// Mirrors SettingsView.vue's own SECTIONS list/order - the accordion below
// is just a second way to reach the same ?tab= deep links.
const SETTINGS_SECTIONS: SettingsSection[] = [
  { value: "general", label: "General", icon: "pi pi-user" },
  { value: "users", label: "Users", icon: "pi pi-users", adminOnly: true },
  { value: "ai", label: "AI Provider", icon: "pi pi-sparkles", adminOnly: true },
  { value: "biometrics", label: "Biometrics", icon: "pi pi-id-card", adminOnly: true },
  { value: "cameras", label: "Cameras", icon: "pi pi-video", adminOnly: true },
  { value: "vehicles", label: "Vehicles", icon: "pi pi-car", adminOnly: true },
  { value: "alerts", label: "Alerts", icon: "pi pi-bell", adminOnly: true },
  { value: "live-view", label: "Live View", icon: "pi pi-eye", adminOnly: true },
  { value: "security-feed", label: "Security Feed", icon: "pi pi-th-large", adminOnly: true },
  { value: "storage", label: "Storage", icon: "pi pi-database", adminOnly: true },
  { value: "about", label: "About", icon: "pi pi-info-circle" },
];

const props = withDefaults(defineProps<{ collapsed?: boolean }>(), { collapsed: false });
const emit = defineEmits<{ navigate: [] }>();

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();

const groups = computed(() =>
  GROUPS.map((group) => ({
    ...group,
    items: group.items.filter((item) => !item.adminOnly || auth.isAdmin),
  })).filter((group) => group.items.length > 0),
);

const isSettingsRoute = computed(() => route.name === "settings");
const activeSettingsTab = computed(() =>
  typeof route.query.tab === "string" ? route.query.tab : "general",
);
const visibleSettingsSections = computed(() =>
  SETTINGS_SECTIONS.filter((section) => !section.adminOnly || auth.isAdmin),
);

const settingsExpanded = ref(isSettingsRoute.value);
watch(
  () => route.name,
  (name) => {
    if (name === "settings") settingsExpanded.value = true;
  },
);

function toggleSettingsAccordion(): void {
  // A collapsed (icon-only) sidebar has no room for a nested list - go
  // straight to Settings instead of trying to expand in place.
  if (props.collapsed) {
    void router.push({ name: "settings" });
    emit("navigate");
    return;
  }
  settingsExpanded.value = !settingsExpanded.value;
}
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

    <div class="nav-group">
      <p
        v-if="!collapsed"
        class="nav-group-label"
      >
        System
      </p>
      <button
        type="button"
        class="nav-item accordion-trigger"
        :class="{ active: isSettingsRoute }"
        :title="collapsed ? 'Settings' : undefined"
        :aria-expanded="!collapsed && settingsExpanded"
        data-testid="settings-accordion-trigger"
        @click="toggleSettingsAccordion"
      >
        <i
          class="pi pi-cog"
          aria-hidden="true"
        />
        <span
          v-show="!collapsed"
          class="accordion-label"
        >Settings</span>
        <i
          v-show="!collapsed"
          class="pi pi-angle-down accordion-chevron"
          :class="{ open: settingsExpanded }"
          aria-hidden="true"
        />
      </button>
      <div
        v-if="!collapsed && settingsExpanded"
        class="accordion-children"
        data-testid="settings-accordion-children"
      >
        <RouterLink
          v-for="section in visibleSettingsSections"
          :key="section.value"
          :to="{ name: 'settings', query: { tab: section.value } }"
          class="nav-item nav-subitem"
          :class="{ active: isSettingsRoute && activeSettingsTab === section.value }"
          @click="emit('navigate')"
        >
          <i
            :class="section.icon"
            aria-hidden="true"
          />
          <span>{{ section.label }}</span>
        </RouterLink>
      </div>
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
  width: 100%;
  padding: 9px 12px;
  margin: 2px 0;
  border: none;
  border-radius: 10px;
  background: none;
  font: inherit;
  font-size: 0.9rem;
  font-weight: 500;
  text-decoration: none;
  color: var(--p-surface-600);
  cursor: pointer;
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

.accordion-trigger {
  text-align: left;
}

.accordion-label {
  flex: 1;
}

.accordion-chevron {
  font-size: 0.85rem !important;
  width: auto !important;
  transition: transform 0.15s ease;
}

.accordion-chevron.open {
  transform: rotate(180deg);
}

.accordion-children {
  display: flex;
  flex-direction: column;
  padding-left: 14px;
  border-left: 1px solid var(--p-surface-200);
  margin: 2px 0 2px 22px;
}

.blink-dark .accordion-children {
  border-left-color: var(--p-surface-800);
}

.nav-subitem {
  font-size: 0.85rem;
  padding: 7px 10px;
}
</style>
