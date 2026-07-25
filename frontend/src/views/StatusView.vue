<script setup lang="ts">
import Button from "primevue/button";
import Skeleton from "primevue/skeleton";
import { onMounted, ref } from "vue";

import { getHealth } from "@/api";
import PageHeader from "@/components/PageHeader.vue";

import type { HealthReport } from "@/api";

type TileState = "ok" | "error" | "unknown";

interface Tile {
  key: keyof Pick<HealthReport, "database" | "redis" | "worker">;
  label: string;
  hint: string;
}

const tiles: Tile[] = [
  { key: "database", label: "Database", hint: "PostgreSQL" },
  { key: "redis", label: "Queue", hint: "Redis" },
  { key: "worker", label: "Worker", hint: "Background jobs" },
];

const report = ref<HealthReport | null>(null);
const failed = ref(false);
const loading = ref(true);

// Status colors are reserved for state and never used alone:
// every tile pairs them with an icon and a text label.
const stateMeta: Record<TileState, { icon: string; label: string }> = {
  ok: { icon: "pi pi-check-circle", label: "Operational" },
  error: { icon: "pi pi-times-circle", label: "Unavailable" },
  unknown: { icon: "pi pi-question-circle", label: "Unknown" },
};

async function refresh(): Promise<void> {
  loading.value = true;
  failed.value = false;
  try {
    report.value = await getHealth();
  } catch {
    failed.value = true;
    report.value = null;
  } finally {
    loading.value = false;
  }
}

function tileState(tile: Tile): TileState {
  return report.value ? report.value[tile.key] : "unknown";
}

onMounted(refresh);
</script>

<template>
  <section>
    <PageHeader
      title="Status"
      description="Health of the platform's core services."
    >
      <template #actions>
        <Button
          label="Refresh"
          icon="pi pi-refresh"
          severity="secondary"
          outlined
          :loading="loading"
          data-testid="refresh"
          @click="refresh"
        />
      </template>
    </PageHeader>

    <div
      v-if="loading"
      class="tile-grid"
      data-testid="loading"
    >
      <Skeleton
        v-for="n in 4"
        :key="n"
        height="110px"
        border-radius="14px"
      />
    </div>

    <template v-else>
      <div class="tile-grid">
        <article
          class="tile"
          :class="failed ? 'state-error' : 'state-ok'"
          data-testid="tile-api"
        >
          <p class="tile-label">
            API
          </p>
          <p class="tile-state">
            <i
              :class="failed ? stateMeta.error.icon : stateMeta.ok.icon"
              aria-hidden="true"
            />
            <span>{{ failed ? "Unreachable" : `Operational · v${report?.version}` }}</span>
          </p>
          <p class="tile-hint">
            FastAPI backend
          </p>
        </article>

        <article
          v-for="tile in tiles"
          :key="tile.key"
          class="tile"
          :class="`state-${tileState(tile)}`"
          :data-testid="`tile-${tile.key}`"
        >
          <p class="tile-label">
            {{ tile.label }}
          </p>
          <p class="tile-state">
            <i
              :class="stateMeta[tileState(tile)].icon"
              aria-hidden="true"
            />
            <span>{{ stateMeta[tileState(tile)].label }}</span>
          </p>
          <p class="tile-hint">
            {{ tile.hint }}
          </p>
        </article>
      </div>
      <p class="status-note">
        Camera statistics, sync history, and storage metrics will appear here once the Blink
        integration is linked.
      </p>
    </template>
  </section>
</template>

<style scoped>
.tile-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 14px;
}

.tile {
  padding: 18px 20px;
  border-radius: 14px;
  border: 1px solid var(--p-surface-200);
  background: var(--p-surface-0);
}

.blink-dark .tile {
  border-color: var(--p-surface-800);
  background: color-mix(in srgb, var(--p-surface-900) 60%, transparent);
}

.tile-label {
  margin: 0;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--p-surface-500);
}

.tile-state {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 10px 0 4px;
  font-size: 1rem;
  font-weight: 600;
}

.state-ok .tile-state {
  color: var(--p-green-600);
}

.blink-dark .state-ok .tile-state {
  color: var(--p-green-400);
}

.state-error .tile-state {
  color: var(--p-red-600);
}

.blink-dark .state-error .tile-state {
  color: var(--p-red-400);
}

.state-unknown .tile-state {
  color: var(--p-surface-500);
}

.tile-hint {
  margin: 0;
  font-size: 0.8rem;
  color: var(--p-surface-500);
}

.status-note {
  margin-top: 20px;
  font-size: 0.85rem;
  color: var(--p-surface-500);
}
</style>
