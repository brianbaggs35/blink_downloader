<script setup lang="ts">
import AppLogo from "./AppLogo.vue";

interface NavItem {
  label: string;
  icon: string;
  to: { name: string };
}

interface NavGroup {
  label: string;
  items: NavItem[];
}

// Order is part of the product spec: Library, Status, Live View, Storage,
// AI, AI Usage, Vehicles, Biometrics, Settings.
const groups: NavGroup[] = [
  {
    label: "Monitor",
    items: [
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

const version = __APP_VERSION__;
</script>

<template>
  <aside class="sidebar">
    <RouterLink
      :to="{ name: 'library' }"
      class="brand"
    >
      <AppLogo :size="34" />
      <span class="brand-text">
        <span class="brand-name">Blink</span>
        <span class="brand-sub">AI Security</span>
      </span>
    </RouterLink>

    <nav
      class="nav"
      aria-label="Primary"
    >
      <div
        v-for="group in groups"
        :key="group.label"
        class="nav-group"
      >
        <p class="nav-group-label">
          {{ group.label }}
        </p>
        <RouterLink
          v-for="item in group.items"
          :key="item.label"
          :to="item.to"
          class="nav-item"
        >
          <i
            :class="item.icon"
            aria-hidden="true"
          />
          <span>{{ item.label }}</span>
        </RouterLink>
      </div>
    </nav>

    <footer class="sidebar-footer">
      <span>Blink AI Security</span>
      <span class="version">v{{ version }}</span>
    </footer>
  </aside>
</template>

<style scoped>
.sidebar {
  display: flex;
  flex-direction: column;
  width: var(--app-sidebar-width);
  min-width: var(--app-sidebar-width);
  height: 100vh;
  position: sticky;
  top: 0;
  background: var(--p-surface-0);
  border-right: 1px solid var(--p-surface-200);
}

.blink-dark .sidebar {
  background: color-mix(in srgb, var(--p-surface-900) 65%, var(--p-surface-950));
  border-right-color: var(--p-surface-800);
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 18px 20px;
  text-decoration: none;
}

.brand-text {
  display: flex;
  flex-direction: column;
  line-height: 1.15;
}

.brand-name {
  font-weight: 700;
  font-size: 1.05rem;
  letter-spacing: 0.01em;
  color: var(--p-surface-900);
}

.blink-dark .brand-name {
  color: var(--p-surface-0);
}

.brand-sub {
  font-size: 0.7rem;
  font-weight: 600;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--p-primary-500);
}

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

.nav-item.router-link-active {
  background: color-mix(in srgb, var(--p-primary-500) 12%, transparent);
  color: var(--p-primary-600);
  box-shadow: inset 2px 0 0 var(--p-primary-500);
}

.blink-dark .nav-item.router-link-active {
  color: var(--p-primary-300);
}

.sidebar-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 20px;
  border-top: 1px solid var(--p-surface-200);
  font-size: 0.7rem;
  color: var(--p-surface-500);
}

.blink-dark .sidebar-footer {
  border-top-color: var(--p-surface-800);
}

.version {
  font-variant-numeric: tabular-nums;
}
</style>
