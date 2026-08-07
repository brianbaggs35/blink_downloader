<script setup lang="ts">
/** A single-series line+area trend chart with a per-point hover/focus
 * tooltip. Kept series-agnostic (tokens vs. cost) via props so AiUsageView
 * can mount it twice with different data, color, and formatting. */
import { computed, ref } from "vue";

export interface TrendPoint {
  date: string;
  value: number;
  calls: number;
}

const props = withDefaults(
  defineProps<{
    title: string;
    points: TrendPoint[];
    seriesColor: "blue" | "orange";
    formatValue: (value: number) => string;
    /** Unit for the secondary tooltip line, e.g. "call(s)" or "clip(s)". */
    unitLabel?: string;
  }>(),
  { unitLabel: "call(s)" },
);

const CHART_W = 100;
const CHART_H = 32;

const hoveredIndex = ref<number | null>(null);

function dayLabel(dateStr: string): string {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${dateStr}T00:00:00Z`));
}

const maxValue = computed(() => Math.max(1, ...props.points.map((p) => p.value)));

const coords = computed(() =>
  props.points.map((point, index) => ({
    x:
      props.points.length > 1
        ? (index / (props.points.length - 1)) * CHART_W
        : CHART_W / 2,
    y: CHART_H - (point.value / maxValue.value) * CHART_H,
  })),
);

// Only read behind the same points.length===0 guard as areaPath.
const bandWidth = computed(() => CHART_W / props.points.length);

const linePath = computed(() =>
  coords.value.map((c, i) => `${i === 0 ? "M" : "L"} ${c.x} ${c.y}`).join(" "),
);

// Only rendered behind the template's points.length===0 guard, so coords
// always has at least one entry here.
const areaPath = computed(() => {
  const first = coords.value[0]!;
  const last = coords.value[coords.value.length - 1]!;
  return `${linePath.value} L ${last.x} ${CHART_H} L ${first.x} ${CHART_H} Z`;
});

// hover()/clearHover() are the only writers of hoveredIndex, and hover()
// only ever receives a valid in-bounds index from the v-for below, so a
// non-null hoveredIndex always resolves to a real point/coord.
const hoveredPoint = computed(() =>
  hoveredIndex.value === null ? null : props.points[hoveredIndex.value]!,
);
const hoveredCoord = computed(() =>
  hoveredIndex.value === null ? null : coords.value[hoveredIndex.value]!,
);

function hover(index: number): void {
  hoveredIndex.value = index;
}

function clearHover(): void {
  hoveredIndex.value = null;
}
</script>

<template>
  <figure
    class="chart"
    :class="`series-${seriesColor}`"
  >
    <figcaption class="chart-title">
      {{ title }}
    </figcaption>

    <div
      v-if="points.length === 0"
      class="chart-empty"
      data-testid="chart-empty"
    >
      No data for this period.
    </div>

    <div
      v-else
      class="chart-body"
    >
      <div class="y-axis">
        <span>{{ formatValue(maxValue) }}</span>
        <span>0</span>
      </div>

      <div class="plot">
        <svg
          class="plot-svg"
          :viewBox="`0 0 ${CHART_W} ${CHART_H}`"
          preserve-aspect-ratio="none"
        >
          <line
            class="baseline"
            x1="0"
            :y1="CHART_H"
            :x2="CHART_W"
            :y2="CHART_H"
          />
          <path
            class="area"
            :d="areaPath"
          />
          <path
            class="line"
            :d="linePath"
          />
          <line
            v-if="hoveredCoord"
            class="crosshair"
            :x1="hoveredCoord.x"
            y1="0"
            :x2="hoveredCoord.x"
            :y2="CHART_H"
          />
          <circle
            v-if="hoveredCoord"
            class="marker"
            :cx="hoveredCoord.x"
            :cy="hoveredCoord.y"
            r="1.8"
          />
        </svg>

        <div
          v-for="(point, index) in points"
          :key="point.date"
          class="hit-band"
          :style="{ left: `${(index / points.length) * 100}%`, width: `${(bandWidth / CHART_W) * 100}%` }"
          role="button"
          tabindex="0"
          :data-testid="`hit-${index}`"
          :aria-label="`${dayLabel(point.date)}: ${formatValue(point.value)}`"
          @mouseenter="hover(index)"
          @mouseleave="clearHover"
          @focus="hover(index)"
          @blur="clearHover"
          @keydown.enter="hover(index)"
          @keydown.space.prevent="hover(index)"
        />

        <div
          v-if="hoveredPoint && hoveredCoord"
          class="tooltip"
          :style="{ left: `${(hoveredCoord.x / CHART_W) * 100}%` }"
          data-testid="chart-tooltip"
        >
          <span class="tooltip-date">{{ dayLabel(hoveredPoint.date) }}</span>
          <span class="tooltip-value">{{ formatValue(hoveredPoint.value) }}</span>
          <span class="tooltip-calls">{{ hoveredPoint.calls }} {{ unitLabel }}</span>
        </div>
      </div>
    </div>

    <div
      v-if="points.length > 0"
      class="x-axis"
    >
      <span>{{ dayLabel(points[0]!.date) }}</span>
      <span>{{ dayLabel(points[points.length - 1]!.date) }}</span>
    </div>
  </figure>
</template>

<style scoped>
.chart {
  margin: 0;
  --series-line: var(--p-primary-500);
  --series-area: color-mix(in srgb, var(--p-primary-500) 10%, transparent);
}

.chart.series-blue {
  --series-line: #2a78d6;
  --series-area: color-mix(in srgb, #2a78d6 10%, transparent);
}

.blink-dark .chart.series-blue {
  --series-line: #3987e5;
  --series-area: color-mix(in srgb, #3987e5 10%, transparent);
}

.chart.series-orange {
  --series-line: #eb6834;
  --series-area: color-mix(in srgb, #eb6834 10%, transparent);
}

.blink-dark .chart.series-orange {
  --series-line: #d95926;
  --series-area: color-mix(in srgb, #d95926 10%, transparent);
}

.chart-title {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--p-surface-600);
  margin-bottom: 10px;
}

.blink-dark .chart-title {
  color: var(--p-surface-300);
}

.chart-empty {
  padding: 24px 0;
  font-size: 0.82rem;
  color: var(--p-surface-500);
}

.chart-body {
  display: flex;
  gap: 8px;
  height: 120px;
}

.y-axis {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  font-size: 0.7rem;
  color: var(--p-surface-500);
  text-align: right;
  padding: 2px 0;
  min-width: 40px;
}

.plot {
  position: relative;
  flex: 1;
}

.plot-svg {
  width: 100%;
  height: 100%;
  overflow: visible;
}

.baseline {
  stroke: var(--p-surface-200);
  stroke-width: 0.3;
}

.blink-dark .baseline {
  stroke: var(--p-surface-700);
}

.area {
  fill: var(--series-area);
  stroke: none;
}

.line {
  fill: none;
  stroke: var(--series-line);
  stroke-width: 0.6;
  stroke-linejoin: round;
  stroke-linecap: round;
}

.crosshair {
  stroke: var(--p-surface-400);
  stroke-width: 0.25;
}

.marker {
  fill: var(--series-line);
  stroke: var(--p-surface-0);
  stroke-width: 0.6;
}

.blink-dark .marker {
  stroke: var(--p-surface-900);
}

.hit-band {
  position: absolute;
  top: 0;
  height: 100%;
  cursor: crosshair;
  background: transparent;
}

.hit-band:focus-visible {
  outline: 2px solid var(--series-line);
  outline-offset: -2px;
}

.tooltip {
  position: absolute;
  bottom: calc(100% + 6px);
  transform: translateX(-50%);
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

.blink-dark .tooltip {
  background: var(--p-surface-100);
  color: var(--p-surface-900);
}

.tooltip-date {
  color: rgba(255, 255, 255, 0.7);
}

.blink-dark .tooltip-date {
  color: rgba(0, 0, 0, 0.6);
}

.tooltip-value {
  font-weight: 700;
  font-size: 0.85rem;
}

.tooltip-calls {
  color: rgba(255, 255, 255, 0.7);
}

.blink-dark .tooltip-calls {
  color: rgba(0, 0, 0, 0.6);
}

.x-axis {
  display: flex;
  justify-content: space-between;
  margin-top: 6px;
  margin-left: 48px;
  font-size: 0.7rem;
  color: var(--p-surface-500);
}
</style>
