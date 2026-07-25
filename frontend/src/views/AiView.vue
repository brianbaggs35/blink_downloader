<script setup lang="ts">
import Button from "primevue/button";
import Skeleton from "primevue/skeleton";
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import { ApiError, getAiStats } from "@/api";
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
import { useAuthStore } from "@/stores/auth";

import type { AiStatsResponse } from "@/api";

const router = useRouter();
const auth = useAuthStore();

const stats = ref<AiStatsResponse | null>(null);
const loading = ref(true);
const loadError = ref("");

async function load(): Promise<void> {
  loading.value = true;
  loadError.value = "";
  try {
    stats.value = await getAiStats();
  } catch (caught) {
    loadError.value = caught instanceof ApiError ? caught.message : "Could not load AI stats.";
  } finally {
    loading.value = false;
  }
}

onMounted(load);

// Every call site is already behind a total>0 guard in the template
// (the empty state for zero analyses, and the no-feedback message).
function pct(count: number, total: number): string {
  return `${Math.round((count / total) * 100)}%`;
}
</script>

<template>
  <section>
    <PageHeader
      title="AI"
      description="How your clips are being analyzed: detection activity and feedback accuracy."
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
      data-testid="ai-loading"
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
      title="Couldn't load AI stats"
      description="We weren't able to reach the server. Check your connection and try again."
      data-testid="ai-load-error"
    >
      <template #actions>
        <Button
          label="Retry"
          icon="pi pi-refresh"
          severity="secondary"
          outlined
          data-testid="retry-stats"
          @click="load"
        />
      </template>
    </EmptyState>

    <EmptyState
      v-else-if="stats && stats.total_analyzed === 0"
      icon="pi pi-sparkles"
      title="No clips analyzed yet"
      description="Once AI analysis is enabled and clips come in, activity and accuracy will show up here."
      data-testid="ai-empty"
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

    <template v-else-if="stats">
      <div class="section">
        <h3 class="section-title">
          Activity
        </h3>
        <div class="grid">
          <article class="tile">
            <span class="tile-value">{{ stats.total_analyzed }}</span>
            <span class="tile-label">Clips analyzed</span>
          </article>
          <article class="tile">
            <span class="tile-value">{{ stats.analyzed_last_7_days }}</span>
            <span class="tile-label">In the last 7 days</span>
          </article>
          <article class="tile">
            <span class="tile-value">{{ stats.escalated_count }}</span>
            <span class="tile-label">Escalated to Tier 2</span>
          </article>
          <article class="tile">
            <span class="tile-value">{{ stats.vehicle_proximity_breaches }}</span>
            <span class="tile-label">Vehicle proximity breaches</span>
          </article>
        </div>
      </div>

      <div class="section">
        <h3 class="section-title">
          Suspicion breakdown
        </h3>
        <div
          class="bar"
          data-testid="suspicion-bar"
        >
          <div
            class="bar-segment routine"
            :style="{ width: pct(stats.routine_count, stats.total_analyzed) }"
          />
          <div
            class="bar-segment uncertain"
            :style="{ width: pct(stats.uncertain_count, stats.total_analyzed) }"
          />
          <div
            class="bar-segment suspicious"
            :style="{ width: pct(stats.suspicious_count, stats.total_analyzed) }"
          />
        </div>
        <div class="legend">
          <span class="legend-item">
            <i class="dot routine" />
            Routine — {{ stats.routine_count }} ({{ pct(stats.routine_count, stats.total_analyzed) }})
          </span>
          <span class="legend-item">
            <i class="dot uncertain" />
            Uncertain — {{ stats.uncertain_count }} ({{ pct(stats.uncertain_count, stats.total_analyzed) }})
          </span>
          <span class="legend-item">
            <i class="dot suspicious" />
            Suspicious — {{ stats.suspicious_count }} ({{ pct(stats.suspicious_count, stats.total_analyzed) }})
          </span>
        </div>
      </div>

      <div class="section">
        <h3 class="section-title">
          Feedback accuracy
        </h3>
        <p
          v-if="stats.total_feedback === 0"
          class="muted"
          data-testid="no-feedback"
        >
          No feedback recorded yet. Rate analyses from a clip's detail view to help the AI learn
          what's normal for your cameras.
        </p>
        <div
          v-else
          class="grid"
        >
          <article class="tile">
            <span class="tile-value">{{ pct(stats.correct_feedback, stats.total_feedback) }}</span>
            <span class="tile-label">Accuracy ({{ stats.total_feedback }} rated)</span>
          </article>
          <article class="tile">
            <span class="tile-value">{{ stats.correct_feedback }}</span>
            <span class="tile-label">Confirmed correct</span>
          </article>
          <article class="tile">
            <span class="tile-value">{{ stats.false_positive_feedback }}</span>
            <span class="tile-label">False positives</span>
          </article>
          <article class="tile">
            <span class="tile-value">{{ stats.false_negative_feedback }}</span>
            <span class="tile-label">False negatives</span>
          </article>
        </div>
      </div>
    </template>
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

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 14px;
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

.tile-label {
  font-size: 0.8rem;
  color: var(--p-surface-500);
}

.bar {
  display: flex;
  height: 14px;
  border-radius: 999px;
  overflow: hidden;
  background: var(--p-surface-200);
}

.blink-dark .bar {
  background: var(--p-surface-800);
}

.bar-segment {
  height: 100%;
}

.bar-segment.routine {
  background: var(--p-green-500);
}

.bar-segment.uncertain {
  background: var(--p-yellow-500);
}

.bar-segment.suspicious {
  background: var(--p-red-500);
}

.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-top: 12px;
}

.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 0.82rem;
  color: var(--p-surface-600);
}

.blink-dark .legend-item {
  color: var(--p-surface-300);
}

.dot {
  display: inline-block;
  width: 9px;
  height: 9px;
  border-radius: 50%;
}

.dot.routine {
  background: var(--p-green-500);
}

.dot.uncertain {
  background: var(--p-yellow-500);
}

.dot.suspicious {
  background: var(--p-red-500);
}

.muted {
  font-size: 0.85rem;
  color: var(--p-surface-500);
}
</style>
