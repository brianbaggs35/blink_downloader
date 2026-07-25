import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import UsageTrendChart from "@/components/UsageTrendChart.vue";

import type { TrendPoint } from "@/components/UsageTrendChart.vue";

const points: TrendPoint[] = [
  { date: "2026-07-01", value: 10, calls: 2 },
  { date: "2026-07-02", value: 40, calls: 5 },
  { date: "2026-07-03", value: 25, calls: 3 },
];

function mountChart(props: Partial<InstanceType<typeof UsageTrendChart>["$props"]> = {}) {
  return mount(UsageTrendChart, {
    props: {
      title: "Tokens per day",
      points,
      seriesColor: "blue",
      formatValue: (v: number) => `${v}u`,
      ...props,
    },
  });
}

describe("UsageTrendChart", () => {
  it("shows an empty message when there are no points", () => {
    const wrapper = mountChart({ points: [] });
    expect(wrapper.find('[data-testid="chart-empty"]').exists()).toBe(true);
  });

  it("labels the y-axis with the formatted max and a literal zero", () => {
    const wrapper = mountChart();
    const yAxis = wrapper.find(".y-axis");
    expect(yAxis.text()).toContain("40u");
    expect(yAxis.text()).toContain("0");
  });

  it("labels the x-axis with the first and last day, formatted in UTC", () => {
    const wrapper = mountChart();
    const xAxis = wrapper.find(".x-axis");
    expect(xAxis.text()).toContain("Jul 1");
    expect(xAxis.text()).toContain("Jul 3");
  });

  it("draws no crosshair or marker until something is hovered", () => {
    const wrapper = mountChart();
    expect(wrapper.find(".crosshair").exists()).toBe(false);
    expect(wrapper.find(".marker").exists()).toBe(false);
    expect(wrapper.find('[data-testid="chart-tooltip"]').exists()).toBe(false);
  });

  it("shows the crosshair, marker, and tooltip on hover, and hides them on mouseleave", async () => {
    const wrapper = mountChart();
    await wrapper.find('[data-testid="hit-1"]').trigger("mouseenter");
    expect(wrapper.find(".crosshair").exists()).toBe(true);
    expect(wrapper.find(".marker").exists()).toBe(true);
    const tooltip = wrapper.find('[data-testid="chart-tooltip"]');
    expect(tooltip.text()).toContain("Jul 2");
    expect(tooltip.text()).toContain("40u");
    expect(tooltip.text()).toContain("5 call(s)");

    await wrapper.find('[data-testid="hit-1"]').trigger("mouseleave");
    expect(wrapper.find('[data-testid="chart-tooltip"]').exists()).toBe(false);
  });

  it("shows the same tooltip on keyboard focus, and hides it on blur", async () => {
    const wrapper = mountChart();
    await wrapper.find('[data-testid="hit-0"]').trigger("focus");
    expect(wrapper.find('[data-testid="chart-tooltip"]').text()).toContain("10u");
    await wrapper.find('[data-testid="hit-0"]').trigger("blur");
    expect(wrapper.find('[data-testid="chart-tooltip"]').exists()).toBe(false);
  });

  it("centers a single data point instead of dividing by zero", () => {
    const wrapper = mountChart({ points: [{ date: "2026-07-01", value: 5, calls: 1 }] });
    const line = wrapper.find(".line");
    expect(line.attributes("d")).not.toContain("NaN");
  });

  it("applies the orange series class when requested", () => {
    const wrapper = mountChart({ seriesColor: "orange" });
    expect(wrapper.find(".chart").classes()).toContain("series-orange");
  });
});
