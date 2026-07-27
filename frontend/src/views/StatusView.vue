<script setup lang="ts">
import Button from "primevue/button";
import Message from "primevue/message";
import Skeleton from "primevue/skeleton";
import Tag from "primevue/tag";
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import { getHealth } from "@/api";
import PageHeader from "@/components/PageHeader.vue";
import UsageTrendChart from "@/components/UsageTrendChart.vue";
import { useFormatting } from "@/composables/useFormatting";
import { useBlinkStore } from "@/stores/blink";

import type { HealthReport } from "@/api";
import type { TrendPoint } from "@/components/UsageTrendChart.vue";

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

const router = useRouter();
const blink = useBlinkStore();
const { formatDateTime } = useFormatting();

const report = ref<HealthReport | null>(null);
const failed = ref(false);
const loading = ref(true);
const blinkError = ref("");

// Status colors are reserved for state and never used alone:
// every tile pairs them with an icon and a text label.
const stateMeta: Record<TileState, { icon: string; label: string }> = {
  ok: { icon: "pi pi-check-circle", label: "Operational" },
  error: { icon: "pi pi-times-circle", label: "Unavailable" },
  unknown: { icon: "pi pi-question-circle", label: "Unknown" },
};

async function refreshHealth(): Promise<void> {
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

async function refreshBlink(): Promise<void> {
  blinkError.value = "";
  try {
    await blink.refreshStatus();
  } catch {
    blinkError.value = "Could not check your Blink connection status.";
  }
}

function refreshAll(): void {
  void refreshHealth();
  void refreshBlink();
}

function tileState(tile: Tile): TileState {
  return report.value ? report.value[tile.key] : "unknown";
}

const connectionSeverity = computed(() => {
  if (!blink.status?.linked) return "secondary";
  return blink.status.status === "active" ? "success" : "danger";
});

const connectionLabel = computed(() => {
  if (!blink.status?.linked) return "Not connected";
  return blink.status.status === "active" ? "Connected" : "Needs attention";
});

const dailyPoints = computed<TrendPoint[]>(() =>
  (blink.status?.daily_clip_counts ?? []).map((day) => ({
    date: day.date,
    value: day.count,
    calls: day.count,
  })),
);

const clipsToday = computed(() => {
  const days = blink.status?.daily_clip_counts ?? [];
  return days.length > 0 ? days[days.length - 1].count : 0;
});

const clipsThisWeek = computed(() =>
  (blink.status?.daily_clip_counts ?? []).reduce((sum, day) => sum + day.count, 0),
);

const networkIds = computed(() => blink.status?.network_ids ?? []);

function goToBlinkSettings(): void {
  void router.push({ name: "settings", query: { tab: "general" } });
}

onMounted(refreshAll);
</script>

<template>
  <section>
    <PageHeader
      title="Status"
      description="Your Blink connection, recent activity, and the platform's core services."
    >
      <template #actions>
        <Button
          label="Refresh"
          icon="pi pi-refresh"
          severity="secondary"
          outlined
          :loading="loading || blink.loading"
          data-testid="refresh"
          @click="refreshAll"
        />
      </template>
    </PageHeader>

    <div class="section">
      <h3 class="section-title">
        Blink Connection
      </h3>

      <div
        v-if="blink.loading && !blink.status"
        data-testid="blink-loading"
      >
        <Skeleton
          height="90px"
          border-radius="14px"
        />
      </div>

      <div
        v-else-if="blinkError"
        data-testid="blink-error"
      >
        <Message
          severity="error"
          :closable="false"
        >
          {{ blinkError }}
        </Message>
        <div class="connection-actions">
          <Button
            label="Retry"
            severity="secondary"
            outlined
            data-testid="retry-blink"
            @click="refreshBlink"
          />
        </div>
      </div>

      <template v-else>
        <article
          class="connection-card"
          data-testid="connection-card"
        >
          <div class="connection-row">
            <Tag
              :value="connectionLabel"
              :severity="connectionSeverity"
              data-testid="connection-tag"
            />
            <p
              v-if="blink.status?.linked && blink.status.last_sync"
              class="muted"
            >
              Last synced {{ formatDateTime(blink.status.last_sync) }}
            </p>
            <p
              v-else-if="!blink.status?.linked"
              class="muted"
            >
              Link a Blink account to start syncing cameras and clips.
            </p>
          </div>
          <p
            v-if="networkIds.length > 0"
            class="muted"
            data-testid="network-ids"
          >
            {{ networkIds.length === 1 ? "Network ID" : "Network IDs" }}:
            {{ networkIds.join(", ") }}
          </p>
          <Message
            v-if="blink.status?.last_error"
            severity="error"
            :closable="false"
            data-testid="connection-last-error"
          >
            {{ blink.status.last_error }}
          </Message>
          <div class="connection-actions">
            <Button
              :label="blink.status?.linked ? 'Manage in Settings' : 'Connect Blink account'"
              icon="pi pi-cog"
              severity="secondary"
              outlined
              data-testid="manage-blink"
              @click="goToBlinkSettings"
            />
          </div>
        </article>

        <div class="stat-grid">
          <article class="stat-tile">
            <span class="stat-value">{{ blink.status?.total_clip_count ?? 0 }}</span>
            <span class="stat-label">Total clips downloaded</span>
          </article>
          <article class="stat-tile">
            <span class="stat-value">{{ blink.status?.camera_count ?? 0 }}</span>
            <span class="stat-label">Cameras</span>
          </article>
          <article class="stat-tile">
            <span
              class="stat-value"
              data-testid="clips-today"
            >{{ clipsToday }}</span>
            <span class="stat-label">Clips today</span>
          </article>
          <article class="stat-tile">
            <span
              class="stat-value"
              data-testid="clips-this-week"
            >{{ clipsThisWeek }}</span>
            <span class="stat-label">Clips this week</span>
          </article>
        </div>

        <UsageTrendChart
          title="Clips downloaded — last 7 days"
          :points="dailyPoints"
          series-color="blue"
          unit-label="clip(s)"
          :format-value="(v) => Math.round(v).toLocaleString()"
        />
      </template>
    </div>

    <div class="section">
      <h3 class="section-title">
        Platform Health
      </h3>

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

      <div
        v-else
        class="tile-grid"
      >
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
    </div>
  </section>
</template>

<style scoped>
.section {
  margin-bottom: 28px;
}

.section-title {
  margin: 0 0 12px;
  font-size: 0.85rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--p-surface-500);
}

.connection-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 18px 20px;
  margin-bottom: 14px;
  border-radius: 14px;
  border: 1px solid var(--p-surface-200);
  background: var(--p-surface-0);
}

.blink-dark .connection-card {
  border-color: var(--p-surface-800);
  background: color-mix(in srgb, var(--p-surface-900) 60%, transparent);
}

.connection-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.connection-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}

.muted {
  margin: 0;
  font-size: 0.85rem;
  color: var(--p-surface-500);
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 14px;
  margin-bottom: 18px;
}

.stat-tile {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 18px 20px;
  border-radius: 14px;
  border: 1px solid var(--p-surface-200);
  background: var(--p-surface-0);
}

.blink-dark .stat-tile {
  border-color: var(--p-surface-800);
  background: color-mix(in srgb, var(--p-surface-900) 60%, transparent);
}

.stat-value {
  font-size: 1.7rem;
  font-weight: 700;
  letter-spacing: -0.02em;
}

.stat-label {
  font-size: 0.8rem;
  color: var(--p-surface-500);
}

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
</style>
