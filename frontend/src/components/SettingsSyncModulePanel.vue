<script setup lang="ts">
import Message from "primevue/message";
import Skeleton from "primevue/skeleton";
import Tag from "primevue/tag";
import { onMounted, ref } from "vue";

import { ApiError, listSyncModules } from "@/api";

import type { SyncModuleRead } from "@/api";

const syncModules = ref<SyncModuleRead[]>([]);
const loading = ref(true);
const loadError = ref("");

async function load(): Promise<void> {
  loading.value = true;
  loadError.value = "";
  try {
    syncModules.value = await listSyncModules();
  } catch (caught) {
    loadError.value =
      caught instanceof ApiError ? caught.message : "Could not load Sync Modules.";
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<template>
  <article class="panel">
    <h3 class="panel-title">
      Sync Module
    </h3>
    <p class="panel-hint">
      Read-only identity for each Sync Module on your Blink account. Arming, motion detection,
      and local storage are controlled from the Sync Module page.
    </p>

    <div
      v-if="loading"
      data-testid="settings-sync-modules-loading"
    >
      <Skeleton
        height="100px"
        border-radius="10px"
      />
    </div>

    <Message
      v-else-if="loadError"
      severity="error"
      :closable="false"
      data-testid="settings-sync-modules-error"
    >
      {{ loadError }}
    </Message>

    <Message
      v-else-if="syncModules.length === 0"
      severity="info"
      :closable="false"
      data-testid="settings-sync-modules-empty"
    >
      No Sync Modules yet. Link your Blink account in the General tab and sync at least once.
    </Message>

    <div
      v-else
      class="sync-module-list"
      data-testid="settings-sync-module-list"
    >
      <article
        v-for="syncModule in syncModules"
        :key="syncModule.id"
        class="sync-module-row"
        :data-testid="`settings-sync-module-row-${syncModule.id}`"
      >
        <div class="row-header">
          <span class="sync-module-name">{{ syncModule.name }}</span>
          <Tag
            :value="syncModule.online ? 'Online' : 'Offline'"
            :severity="syncModule.online ? 'success' : 'danger'"
          />
        </div>
        <dl class="identity-grid">
          <div class="identity-field">
            <dt>Serial</dt>
            <dd>{{ syncModule.serial ?? "—" }}</dd>
          </div>
          <div class="identity-field">
            <dt>Firmware</dt>
            <dd>{{ syncModule.firmware_version ?? "—" }}</dd>
          </div>
          <div class="identity-field">
            <dt>Physical hub</dt>
            <dd>{{ syncModule.is_physical_hub ? "Yes" : "No" }}</dd>
          </div>
          <div class="identity-field">
            <dt>Local storage</dt>
            <dd>
              {{
                syncModule.local_storage_compatible
                  ? syncModule.local_storage_enabled
                    ? "Enabled"
                    : "Supported, not enabled"
                  : "Not supported"
              }}
            </dd>
          </div>
        </dl>
      </article>
    </div>
  </article>
</template>

<style scoped>
.panel {
  padding: 22px 24px;
  border-radius: 14px;
  border: 1px solid var(--p-surface-200);
  background: var(--p-surface-0);
}

.blink-dark .panel {
  border-color: var(--p-surface-800);
  background: color-mix(in srgb, var(--p-surface-900) 60%, transparent);
}

.panel-title {
  margin: 0;
  font-size: 1rem;
  font-weight: 700;
}

.panel-hint {
  margin: 4px 0 16px;
  font-size: 0.82rem;
  color: var(--p-surface-500);
  max-width: 70ch;
}

.sync-module-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.sync-module-row {
  padding: 16px;
  border-radius: 10px;
  background: var(--p-surface-50);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.blink-dark .sync-module-row {
  background: color-mix(in srgb, var(--p-surface-800) 55%, transparent);
}

.row-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.sync-module-name {
  font-size: 0.92rem;
  font-weight: 600;
}

.identity-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 12px;
  margin: 0;
}

.identity-field {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.identity-field dt {
  font-size: 0.72rem;
  color: var(--p-surface-500);
}

.identity-field dd {
  margin: 0;
  font-size: 0.88rem;
  font-weight: 600;
}
</style>
