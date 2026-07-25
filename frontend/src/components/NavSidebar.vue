<script setup lang="ts">
import Drawer from "primevue/drawer";

import { useMobileNav } from "@/composables/useMobileNav";
import AppLogo from "./AppLogo.vue";
import NavLinks from "./NavLinks.vue";

const mobileNav = useMobileNav();

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

    <NavLinks />

    <footer class="sidebar-footer">
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
