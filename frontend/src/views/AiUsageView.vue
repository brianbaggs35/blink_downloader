<script setup lang="ts">
import Button from "primevue/button";
import SelectButton from "primevue/selectbutton";
import Skeleton from "primevue/skeleton";
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import { ApiError, getAiUsage } from "@/api";
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
import UsageTrendChart from "@/components/UsageTrendChart.vue";
import { useAuthStore } from "@/stores/auth";

import type { AiUsageResponse } from "@/api";

const VIEW_OPTIONS = [
  { label: "Chart", value: "chart" },
  { label: "Table", value: "table" },
];

const router = useRouter();
const auth = useAuthStore();

const usage = ref<AiUsageResponse | null>(null);
const loading = ref(true);
const loadError = ref("");

async function load(): Promise<void> {
  loading.value = true;
  loadError.value = "";
  try {
    usage.value = await getAiUsage();
  } catch (caught) {
    loadError.value = caught instanceof ApiError ? caught.message : "Could not load AI usage.";
  } finally {
    loading.value = false;
  }
}

onMounted(load);

const dailyView = ref<"chart" | "table">("chart");
const providerView = ref<"chart" | "table">("chart");

function formatCompact(n: number): string {
  if (n >= 1_000_000) {
    return `${(n / 1_000_000).toFixed(1)}M`;
  }
  if (n >= 1_000) {
    return `${(n / 1_000).toFixed(1)}K`;
  }
  return n.toLocaleString();
}

function formatCost(n: number): string {
  if (n >= 1000) {
    return `$${formatCompact(n)}`;
  }
  return `$${n.toFixed(2)}`;
}

// tokenPoints/costPoints/byProviderSorted are only read behind the
// template's v-else-if="usage" guard, so usage.value is never null here.
const tokenPoints = computed(
  () => usage.value!.daily.map((d) => ({ date: d.date, value: d.tokens, calls: d.calls })),
);
const costPoints = computed(
  () => usage.value!.daily.map((d) => ({ date: d.date, value: d.cost_usd, calls: d.calls })),
);

const byProviderSorted = computed(() =>
  [...usage.value!.by_provider].sort((a, b) => b.cost_usd - a.cost_usd),
);
const maxProviderCost = computed(() =>
  Math.max(1, ...byProviderSorted.value.map((p) => p.cost_usd)),
);

const hoveredProvider = ref<number | null>(null);
</script>

<template>
  <section>
    <PageHeader
      title="AI Usage"
      description="Token consumption, request volume, and cost per provider, over the last 30 days."
    >
      <template #actions>
        <Button
          v-if="auth.isAdmin"
          label="AI Provider settings"
          icon="pi pi-cog"
          severity="secondary"
          outlined
          data-testid="go-ai-settings"
          @click="router.push({ name: 'settings', query: { tab: 'ai' } })"
        />
      </template>
    </PageHeader>

    <div
      v-if="loading"
      class="grid"
      data-testid="usage-loading"
    >
      <Skeleton
        v-for="n in 4"
        :key="n"
        height="96px"
        border-radius="12px"
      />
    </div>

    <EmptyState
      v-else-if="loadError"
      icon="pi pi-exclamation-triangle"
      title="Couldn't load AI usage"
      description="We weren't able to reach the server. Check your connection and try again."
      data-testid="usage-load-error"
    >
      <template #actions>
        <Button
          label="Retry"
          icon="pi pi-refresh"
          severity="secondary"
          outlined
          data-testid="retry-usage"
          @click="load"
        />
      </template>
    </EmptyState>

    <EmptyState
      v-else-if="usage && usage.total_calls === 0"
      icon="pi pi-chart-bar"
      title="No AI usage yet"
      description="Once clips start getting analyzed, token and cost activity will show up here."
      data-testid="usage-empty"
    >
      <template #actions>
        <Button
          v-if="auth.isAdmin"
          label="Set up AI Provider"
          icon="pi pi-cog"
          data-testid="go-ai-settings-empty"
          @click="router.push({ name: 'settings', query: { tab: 'ai' } })"
        />
      </template>
    </EmptyState>

    <template v-else-if="usage">
      <div class="grid kpis">
        <article class="tile">
          <span class="tile-value">{{ formatCompact(usage.total_tokens) }}</span>
          <span class="tile-label">Total tokens</span>
        </article>
        <article class="tile">
          <span class="tile-value">{{ formatCost(usage.total_cost_usd) }}</span>
          <span class="tile-label">Total cost</span>
        </article>
        <article class="tile">
          <span class="tile-value">{{ usage.total_calls }}</span>
          <span class="tile-label">Total calls</span>
        </article>
        <article class="tile">
          <span class="tile-value">{{ formatCompact(usage.frames_analyzed_today) }}</span>
          <span class="tile-label">Frames analyzed today</span>
        </article>
        <article class="tile">
          <span class="tile-value">{{ formatCompact(usage.total_frames_analyzed) }}</span>
          <span class="tile-label">Frames analyzed (all time)</span>
        </article>
        <article class="tile">
          <span
            class="tile-value"
            :class="{ critical: usage.failed_calls > 0 }"
          >{{ usage.failed_calls }}</span>
          <span class="tile-label">Failed calls</span>
        </article>
      </div>

      <div class="section">
        <div class="section-heading">
          <h3 class="section-title">
            Daily usage
          </h3>
          <SelectButton
            v-model="dailyView"
            :options="VIEW_OPTIONS"
            option-label="label"
            option-value="value"
            :allow-empty="false"
            data-testid="daily-view-toggle"
          />
        </div>

        <div
          v-if="dailyView === 'chart'"
          class="charts"
          data-testid="daily-charts"
        >
          <UsageTrendChart
            title="Tokens per day"
            :points="tokenPoints"
            series-color="blue"
            :format-value="formatCompact"
          />
          <UsageTrendChart
            title="Cost per day"
            :points="costPoints"
            series-color="orange"
            :format-value="formatCost"
          />
        </div>

        <div
          v-else
          class="table-wrap"
          data-testid="daily-table"
        >
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Tokens</th>
                <th>Cost</th>
                <th>Calls</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="day in usage.daily"
                :key="day.date"
              >
                <td>{{ day.date }}</td>
                <td>{{ day.tokens.toLocaleString() }}</td>
                <td>{{ formatCost(day.cost_usd) }}</td>
                <td>{{ day.calls }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="section">
        <div class="section-heading">
          <h3 class="section-title">
            By provider &amp; model
          </h3>
          <SelectButton
            v-model="providerView"
            :options="VIEW_OPTIONS"
            option-label="label"
            option-value="value"
            :allow-empty="false"
            data-testid="provider-view-toggle"
          />
        </div>

        <div
          v-if="providerView === 'chart'"
          class="bars"
          data-testid="provider-bars"
        >
          <div
            v-for="(entry, index) in byProviderSorted"
            :key="`${entry.provider}-${entry.model}`"
            class="bar-row"
            tabindex="0"
            :data-testid="`bar-row-${index}`"
            @mouseenter="hoveredProvider = index"
            @mouseleave="hoveredProvider = null"
            @focus="hoveredProvider = index"
            @blur="hoveredProvider = null"
          >
            <span class="bar-label">{{ entry.provider }} / {{ entry.model }}</span>
            <div class="bar-track">
              <div
                class="bar-fill"
                :class="{ hovered: hoveredProvider === index }"
                :style="{ width: `${(entry.cost_usd / maxProviderCost) * 100}%` }"
              />
            </div>
            <span class="bar-value">{{ formatCost(entry.cost_usd) }}</span>

            <div
              v-if="hoveredProvider === index"
              class="bar-tooltip"
              data-testid="bar-tooltip"
            >
              <span class="tooltip-value">{{ formatCost(entry.cost_usd) }}</span>
              <span>{{ formatCompact(entry.tokens) }} tokens</span>
              <span>{{ entry.calls }} call(s)</span>
            </div>
          </div>
        </div>

        <div
          v-else
          class="table-wrap"
          data-testid="provider-table"
        >
          <table>
            <thead>
              <tr>
                <th>Provider</th>
                <th>Model</th>
                <th>Tokens</th>
                <th>Cost</th>
                <th>Calls</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="entry in byProviderSorted"
                :key="`${entry.provider}-${entry.model}`"
              >
                <td>{{ entry.provider }}</td>
                <td>{{ entry.model }}</td>
                <td>{{ entry.tokens.toLocaleString() }}</td>
                <td>{{ formatCost(entry.cost_usd) }}</td>
                <td>{{ entry.calls }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.section {
  margin-bottom: 28px;
}

.section-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.section-title {
  margin: 0;
  font-size: 0.85rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--p-surface-500);
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 14px;
}

.kpis {
  margin-bottom: 28px;
}

.tile {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 18px 20px;
  border-radius: 14px;
  border: 1px solid var(--p-surface-200);
  background: var(--p-surface-0);
}

.blink-dark .tile {
  border-color: var(--p-surface-800);
  background: color-mix(in srgb, var(--p-surface-900) 60%, transparent);
}

.tile-value {
  font-size: 1.7rem;
  font-weight: 700;
  letter-spacing: -0.02em;
}

.tile-value.critical {
  color: #d03b3b;
}

.tile-label {
  font-size: 0.8rem;
  color: var(--p-surface-500);
}

.charts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 20px;
  padding: 20px;
  border-radius: 14px;
  border: 1px solid var(--p-surface-200);
  background: var(--p-surface-0);
}

.blink-dark .charts {
  border-color: var(--p-surface-800);
  background: color-mix(in srgb, var(--p-surface-900) 60%, transparent);
}

.table-wrap {
  border-radius: 14px;
  border: 1px solid var(--p-surface-200);
  background: var(--p-surface-0);
  overflow-x: auto;
}

.blink-dark .table-wrap {
  border-color: var(--p-surface-800);
  background: color-mix(in srgb, var(--p-surface-900) 60%, transparent);
}

table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.82rem;
}

th,
td {
  padding: 10px 16px;
  text-align: left;
  font-variant-numeric: tabular-nums;
}

th {
  font-weight: 600;
  color: var(--p-surface-500);
  font-variant-numeric: normal;
  border-bottom: 1px solid var(--p-surface-200);
}

.blink-dark th {
  border-color: var(--p-surface-800);
}

tbody tr + tr td {
  border-top: 1px solid var(--p-surface-100);
}

.blink-dark tbody tr + tr td {
  border-color: var(--p-surface-800);
}

.bars {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 20px;
  border-radius: 14px;
  border: 1px solid var(--p-surface-200);
  background: var(--p-surface-0);
}

.blink-dark .bars {
  border-color: var(--p-surface-800);
  background: color-mix(in srgb, var(--p-surface-900) 60%, transparent);
}

.bar-row {
  position: relative;
  display: grid;
  grid-template-columns: minmax(120px, 220px) 1fr auto;
  align-items: center;
  gap: 12px;
}

.bar-label {
  font-size: 0.82rem;
  color: var(--p-surface-600);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.blink-dark .bar-label {
  color: var(--p-surface-300);
}

.bar-track {
  height: 14px;
  border-radius: 4px;
  background: var(--p-surface-100);
  overflow: hidden;
}

.blink-dark .bar-track {
  background: var(--p-surface-800);
}

.bar-fill {
  height: 100%;
  border-radius: 4px;
  background: #1baf7a;
  transition: opacity 0.15s ease;
}

.blink-dark .bar-fill {
  background: #199e70;
}

.bar-fill.hovered {
  opacity: 0.8;
}

.bar-value {
  font-size: 0.82rem;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  min-width: 4.5rem;
  text-align: right;
}

.bar-tooltip {
  position: absolute;
  top: -8px;
  right: 0;
  transform: translateY(-100%);
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 6px 10px;
  border-radius: 8px;
  background: var(--p-surface-900);
  color: #fff;
  font-size: 0.72rem;
  white-space: nowrap;
  pointer-events: none;
  z-index: 1;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
}

.blink-dark .bar-tooltip {
  background: var(--p-surface-100);
  color: var(--p-surface-900);
}

.bar-tooltip .tooltip-value {
  font-weight: 700;
  font-size: 0.85rem;
}
</style>
