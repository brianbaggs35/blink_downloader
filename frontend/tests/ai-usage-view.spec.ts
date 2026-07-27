import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  getAiUsage: vi.fn(),
}));

import { getAiUsage } from "@/api";
import { ApiError } from "@/api/client";
import { useAuthStore } from "@/stores/auth";
import AiUsageView from "@/views/AiUsageView.vue";
import { fakeUser, makePinia, makeRouter, mountGlobal } from "./helpers";

const mockedUsage = vi.mocked(getAiUsage);

const usage = {
  total_tokens: 1_234_567,
  total_cost_usd: 42.5,
  total_calls: 120,
  failed_calls: 3,
  total_frames_analyzed: 480,
  frames_analyzed_today: 24,
  daily: [
    { date: "2026-07-01", tokens: 1000, cost_usd: 1.1, calls: 5 },
    { date: "2026-07-02", tokens: 4000, cost_usd: 4.4, calls: 8 },
  ],
  by_provider: [
    { provider: "openai", model: "gpt-4o-mini", tokens: 900_000, cost_usd: 30, calls: 90 },
    { provider: "anthropic", model: "claude-haiku-4-5", tokens: 334_567, cost_usd: 12.5, calls: 30 },
  ],
};

const emptyUsage = {
  total_tokens: 0,
  total_cost_usd: 0,
  total_calls: 0,
  failed_calls: 0,
  total_frames_analyzed: 0,
  frames_analyzed_today: 0,
  daily: [],
  by_provider: [],
};

beforeEach(() => {
  vi.clearAllMocks();
});

function mountView(isAdmin = true) {
  const pinia = makePinia();
  useAuthStore().user = { ...fakeUser, is_superuser: isAdmin };
  return mount(AiUsageView, { global: mountGlobal(pinia, makeRouter()) });
}

describe("AiUsageView loading", () => {
  it("shows a loading skeleton while fetching", () => {
    mockedUsage.mockReturnValue(new Promise(() => {}));
    const wrapper = mountView();
    expect(wrapper.find('[data-testid="usage-loading"]').exists()).toBe(true);
  });

  it("shows a retry empty state on failure, and retry reloads", async () => {
    mockedUsage.mockRejectedValueOnce(new ApiError(500, "Server exploded"));
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.find('[data-testid="usage-load-error"]').exists()).toBe(true);

    mockedUsage.mockResolvedValueOnce(usage);
    await wrapper.find('[data-testid="retry-usage"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="usage-load-error"]').exists()).toBe(false);
    expect(wrapper.text()).toContain("Total tokens");
  });

  it("falls back to a generic load error message for non-API failures", async () => {
    mockedUsage.mockRejectedValue(new TypeError("down"));
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.find('[data-testid="usage-load-error"]').text()).toContain(
      "Couldn't load AI usage",
    );
  });

  it("shows an empty state with no usage yet", async () => {
    mockedUsage.mockResolvedValue(emptyUsage);
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.find('[data-testid="usage-empty"]').exists()).toBe(true);
  });

  it("hides AI settings shortcuts from a non-admin", async () => {
    mockedUsage.mockResolvedValue(emptyUsage);
    const wrapper = mountView(false);
    await flushPromises();
    expect(wrapper.find('[data-testid="go-ai-settings"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="go-ai-settings-empty"]').exists()).toBe(false);
  });

  it("links an admin to AI Provider settings from the empty state", async () => {
    mockedUsage.mockResolvedValue(emptyUsage);
    const router = makeRouter();
    const pushSpy = vi.spyOn(router, "push");
    const pinia = makePinia();
    useAuthStore().user = { ...fakeUser, is_superuser: true };
    const wrapper = mount(AiUsageView, { global: mountGlobal(pinia, router) });
    await flushPromises();
    await wrapper.find('[data-testid="go-ai-settings-empty"]').trigger("click");
    expect(pushSpy).toHaveBeenCalledWith({ name: "settings", query: { tab: "ai" } });
  });

  it("links an admin to AI Provider settings from the populated header", async () => {
    mockedUsage.mockResolvedValue(usage);
    const router = makeRouter();
    const pushSpy = vi.spyOn(router, "push");
    const pinia = makePinia();
    useAuthStore().user = { ...fakeUser, is_superuser: true };
    const wrapper = mount(AiUsageView, { global: mountGlobal(pinia, router) });
    await flushPromises();
    await wrapper.find('[data-testid="go-ai-settings"]').trigger("click");
    expect(pushSpy).toHaveBeenCalledWith({ name: "settings", query: { tab: "ai" } });
  });
});

describe("AiUsageView KPI tiles", () => {
  it("compact-formats tokens and cost, and flags failed calls", async () => {
    mockedUsage.mockResolvedValue(usage);
    const wrapper = mountView();
    await flushPromises();
    const text = wrapper.text();
    expect(text).toContain("1.2M");
    expect(text).toContain("Total tokens");
    expect(text).toContain("$42.50");
    expect(text).toContain("120");
    expect(text).toContain("Total calls");
    expect(text).toContain("24");
    expect(text).toContain("Frames analyzed today");
    expect(text).toContain("480");
    expect(text).toContain("Frames analyzed (all time)");
    expect(text).toContain("3");
    expect(text).toContain("Failed calls");
    const failedTile = wrapper.findAll(".tile-value").find((el) => el.text() === "3");
    expect(failedTile?.classes()).toContain("critical");
  });

  it("does not flag zero failed calls as critical", async () => {
    mockedUsage.mockResolvedValue({ ...usage, failed_calls: 0 });
    const wrapper = mountView();
    await flushPromises();
    const failedTile = wrapper.findAll(".tile-value").find((el) => el.text() === "0");
    expect(failedTile?.classes()).not.toContain("critical");
  });

  it("compact-formats a cost of 1000 or more with a K/M suffix", async () => {
    mockedUsage.mockResolvedValue({ ...usage, total_cost_usd: 1500 });
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.text()).toContain("$1.5K");
  });

  it("keeps small token counts as plain grouped numbers", async () => {
    mockedUsage.mockResolvedValue({ ...usage, total_tokens: 500 });
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.text()).toContain("500");
  });
});

describe("AiUsageView daily section", () => {
  beforeEach(() => {
    mockedUsage.mockResolvedValue(usage);
  });

  it("shows two trend charts by default", async () => {
    const wrapper = mountView();
    await flushPromises();
    const charts = wrapper.find('[data-testid="daily-charts"]');
    expect(charts.text()).toContain("Tokens per day");
    expect(charts.text()).toContain("Cost per day");
  });

  it("switches to a table with one row per day", async () => {
    const wrapper = mountView();
    await flushPromises();
    const toggle = wrapper.find('[data-testid="daily-view-toggle"]');
    const tableOption = toggle.findAll(".p-togglebutton")[1]!;
    await tableOption.trigger("click");
    await flushPromises();

    expect(wrapper.find('[data-testid="daily-charts"]').exists()).toBe(false);
    const table = wrapper.find('[data-testid="daily-table"]');
    const rows = table.findAll("tbody tr");
    expect(rows).toHaveLength(2);
    expect(rows[0]!.text()).toContain("2026-07-01");
    expect(rows[0]!.text()).toContain("1,000");
    expect(rows[0]!.text()).toContain("$1.10");
    expect(rows[0]!.text()).toContain("5");
  });
});

describe("AiUsageView provider section", () => {
  beforeEach(() => {
    mockedUsage.mockResolvedValue(usage);
  });

  it("shows bars sorted by cost, descending", async () => {
    const wrapper = mountView();
    await flushPromises();
    const rows = wrapper.findAll('[data-testid^="bar-row-"]');
    expect(rows).toHaveLength(2);
    expect(rows[0]!.text()).toContain("openai / gpt-4o-mini");
    expect(rows[1]!.text()).toContain("anthropic / claude-haiku-4-5");
  });

  it("shows a tooltip with token and call detail on hover, hidden by default", async () => {
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.find('[data-testid="bar-tooltip"]').exists()).toBe(false);

    const firstRow = wrapper.find('[data-testid="bar-row-0"]');
    await firstRow.trigger("mouseenter");
    const tooltip = wrapper.find('[data-testid="bar-tooltip"]');
    expect(tooltip.text()).toContain("$30.00");
    expect(tooltip.text()).toContain("900.0K tokens");
    expect(tooltip.text()).toContain("90 call(s)");

    await firstRow.trigger("mouseleave");
    expect(wrapper.find('[data-testid="bar-tooltip"]').exists()).toBe(false);
  });

  it("shows the tooltip on keyboard focus too", async () => {
    const wrapper = mountView();
    await flushPromises();
    const firstRow = wrapper.find('[data-testid="bar-row-0"]');
    await firstRow.trigger("focus");
    expect(wrapper.find('[data-testid="bar-tooltip"]').exists()).toBe(true);
    await firstRow.trigger("blur");
    expect(wrapper.find('[data-testid="bar-tooltip"]').exists()).toBe(false);
  });

  it("switches to a table sorted by cost, descending", async () => {
    const wrapper = mountView();
    await flushPromises();
    const toggle = wrapper.find('[data-testid="provider-view-toggle"]');
    const tableOption = toggle.findAll(".p-togglebutton")[1]!;
    await tableOption.trigger("click");
    await flushPromises();

    expect(wrapper.find('[data-testid="provider-bars"]').exists()).toBe(false);
    const rows = wrapper.find('[data-testid="provider-table"]').findAll("tbody tr");
    expect(rows).toHaveLength(2);
    expect(rows[0]!.text()).toContain("openai");
    expect(rows[0]!.text()).toContain("gpt-4o-mini");
    expect(rows[0]!.text()).toContain("900,000");
    expect(rows[0]!.text()).toContain("$30.00");
  });
});
