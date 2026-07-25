<script setup lang="ts">
import NavSidebar from "@/components/NavSidebar.vue";
import TopBar from "@/components/TopBar.vue";
</script>

<template>
  <div class="app-shell">
    <NavSidebar />
    <div class="app-main">
      <TopBar />
      <main class="app-content">
        <RouterView />
      </main>
    </div>
  </div>
</template>

<style scoped>
.app-shell {
  display: flex;
  min-height: 100vh;
}

.app-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.app-content {
  flex: 1;
  padding: 28px;
  max-width: calc(var(--app-content-max-width) + 56px);
  width: 100%;
  margin: 0 auto;
}

@media (max-width: 768px) {
  .app-content {
    padding: 16px;
  }
}
</style>
