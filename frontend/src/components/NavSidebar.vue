<script setup lang="ts">
import Drawer from "primevue/drawer";
import { computed, onMounted, onUnmounted } from "vue";

import { useMobileNav } from "@/composables/useMobileNav";
import { useSidebarCollapse } from "@/composables/useSidebarCollapse";
import { useBlinkStore } from "@/stores/blink";
import AppLogo from "./AppLogo.vue";
import NavLinks from "./NavLinks.vue";

const mobileNav = useMobileNav();
const sidebar = useSidebarCollapse();
const blink = useBlinkStore();

const version = __APP_VERSION__;

// A lightweight background ping so the badge stays current even if the
// user never visits Status/Settings this session - failures are silently
// ignored here (the badge just falls back to "Not connected") since a
// nav-wide poll is the wrong place to surface a retry/error UI.
const BLINK_STATUS_POLL_MS = 60_000;
let pollTimer: ReturnType<typeof setInterval> | undefined;

type ConnectionState = "connected" | "attention" | "unlinked";

// Three underlying states still drive the dot's color (an auth error is a
// meaningfully different situation from never having linked at all - worth
// flagging red rather than the same gray as "not connected"), but the label
// itself is deliberately just the two words Brian asked for; the Status
// page is where the actual distinction and detail live.
const connectionState = computed<ConnectionState>(() => {
  if (!blink.status?.linked) return "unlinked";
  return blink.status.status === "active" ? "connected" : "attention";
});

const connectionLabel = computed(() =>
  connectionState.value === "connected" ? "Connected" : "Disconnected",
);

function pollBlinkStatus(): void {
  void blink.refreshStatus().catch(() => undefined);
}

onMounted(() => {
  pollBlinkStatus();
  pollTimer = setInterval(pollBlinkStatus, BLINK_STATUS_POLL_MS);
});

onUnmounted(() => {
  clearInterval(pollTimer);
});
</script>

<template>
  <aside :class="['sidebar', { collapsed: sidebar.isCollapsed.value }]">
    <div class="sidebar-header">
      <RouterLink
        :to="{ name: 'library' }"
        class="brand"
      >
        <AppLogo :size="34" />
        <span
          v-show="!sidebar.isCollapsed.value"
          class="brand-text"
        >
          <span class="brand-name">Blink</span>
          <span class="brand-sub">AI Security</span>
        </span>
      </RouterLink>

      <button
        type="button"
        class="collapse-toggle"
        :title="sidebar.isCollapsed.value ? 'Expand sidebar' : 'Collapse sidebar'"
        :aria-label="sidebar.isCollapsed.value ? 'Expand sidebar' : 'Collapse sidebar'"
        data-testid="sidebar-collapse-toggle"
        @click="sidebar.toggle()"
      >
        <i
          :class="sidebar.isCollapsed.value ? 'pi pi-angle-double-right' : 'pi pi-angle-double-left'"
          aria-hidden="true"
        />
      </button>
    </div>

    <NavLinks :collapsed="sidebar.isCollapsed.value" />

    <div
      class="connection-badge"
      :class="`badge-${connectionState}`"
      :title="connectionLabel"
      data-testid="nav-blink-badge"
    >
      <span
        class="badge-dot"
        aria-hidden="true"
      />
      <span
        v-show="!sidebar.isCollapsed.value"
        class="badge-label"
      >{{ connectionLabel }}</span>
    </div>

    <footer
      v-show="!sidebar.isCollapsed.value"
      class="sidebar-footer"
    >
      <span>Blink AI Security</span>
      <span class="version">v{{ version }}</span>
    </footer>
  </aside>

  <Drawer
    v-model:visible="mobileNav.isOpen.value"
    position="left"
    class="mobile-drawer"
    data-testid="mobile-nav-drawer"
  >
    <template #header>
      <RouterLink
        :to="{ name: 'library' }"
        class="brand"
        @click="mobileNav.close()"
      >
        <AppLogo :size="30" />
        <span class="brand-text">
          <span class="brand-name">Blink</span>
          <span class="brand-sub">AI Security</span>
        </span>
      </RouterLink>
    </template>
    <NavLinks @navigate="mobileNav.close()" />
    <div
      class="connection-badge"
      :class="`badge-${connectionState}`"
      data-testid="nav-blink-badge-mobile"
    >
      <span
        class="badge-dot"
        aria-hidden="true"
      />
      <span class="badge-label">{{ connectionLabel }}</span>
    </div>
    <footer class="sidebar-footer">
      <span>Blink AI Security</span>
      <span class="version">v{{ version }}</span>
    </footer>
  </Drawer>
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
  transition: width 0.18s ease, min-width 0.18s ease;
}

.sidebar.collapsed {
  width: var(--app-sidebar-collapsed-width);
  min-width: var(--app-sidebar-collapsed-width);
}

.blink-dark .sidebar {
  background: color-mix(in srgb, var(--p-surface-900) 65%, var(--p-surface-950));
  border-right-color: var(--p-surface-800);
}

.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-right: 10px;
}

.sidebar.collapsed .sidebar-header {
  flex-direction: column;
  justify-content: center;
  gap: 4px;
  padding-right: 0;
  padding-bottom: 8px;
}

.collapse-toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 30px;
  height: 30px;
  border: none;
  border-radius: 8px;
  background: none;
  color: var(--p-surface-500);
  cursor: pointer;
}

.collapse-toggle i {
  font-size: 0.9rem;
}

.collapse-toggle:hover {
  background: var(--p-surface-100);
  color: var(--p-surface-900);
}

.blink-dark .collapse-toggle:hover {
  background: color-mix(in srgb, var(--p-surface-800) 70%, transparent);
  color: var(--p-surface-100);
}

.connection-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin: 0 12px 4px;
  padding: 5px 10px;
  border-radius: 999px;
  background: var(--p-surface-100);
  font-size: 0.72rem;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
}

.blink-dark .connection-badge {
  background: color-mix(in srgb, var(--p-surface-800) 60%, transparent);
}

.sidebar.collapsed .connection-badge {
  justify-content: center;
  margin-inline: 8px;
  padding-inline: 0;
}

.badge-dot {
  width: 8px;
  height: 8px;
  min-width: 8px;
  border-radius: 50%;
}

.badge-connected .badge-dot {
  background: var(--p-green-500);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--p-green-500) 20%, transparent);
}

.badge-connected .badge-label {
  color: var(--p-green-700);
}

.blink-dark .badge-connected .badge-label {
  color: var(--p-green-400);
}

.badge-attention .badge-dot {
  background: var(--p-red-500);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--p-red-500) 20%, transparent);
}

.badge-attention .badge-label {
  color: var(--p-red-700);
}

.blink-dark .badge-attention .badge-label {
  color: var(--p-red-400);
}

.badge-unlinked .badge-dot {
  background: var(--p-surface-400);
}

.badge-unlinked .badge-label {
  color: var(--p-surface-500);
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 18px 0 18px 20px;
  text-decoration: none;
  min-width: 0;
}

.sidebar.collapsed .brand {
  padding: 18px 0 0;
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

@media (max-width: 768px) {
  .sidebar {
    display: none;
  }
}
</style>

<style>
/* Drawer teleports to document.body, so this can't be `scoped` — it only
 * ever renders below the 768px breakpoint where the static .sidebar is
 * already display:none, so there's no overlap with the desktop styles. */
.mobile-drawer .p-drawer-header {
  padding: 6px 12px;
}

.mobile-drawer .p-drawer-content {
  padding: 0;
  display: flex;
  flex-direction: column;
}

.mobile-drawer .nav {
  padding: 8px 12px 16px;
}

.mobile-drawer .sidebar-footer {
  padding: 14px 20px;
  border-top: 1px solid var(--p-surface-200);
}

.blink-dark .mobile-drawer .sidebar-footer {
  border-top-color: var(--p-surface-800);
}

@media (min-width: 769px) {
  .mobile-drawer {
    display: none;
  }
}
</style>
