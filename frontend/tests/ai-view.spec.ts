import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  getAiStats: vi.fn(),
}));

import { getAiStats } from "@/api";
import { ApiError } from "@/api/client";
import { useAuthStore } from "@/stores/auth";
import AiView from "@/views/AiView.vue";
import { fakeUser, makePinia, makeRouter, mountGlobal } from "./helpers";

const mockedStats = vi.mocked(getAiStats);

const stats = {
  total_analyzed: 40,
  suspicious_count: 4,
  uncertain_count: 6,
  routine_count: 30,
  escalated_count: 8,
  analyzed_last_7_days: 12,
  vehicle_proximity_breaches: 2,
  total_feedback: 10,
  correct_feedback: 8,
  false_positive_feedback: 1,
  false_negative_feedback: 1,
};

const emptyStats = {
  total_analyzed: 0,
  suspicious_count: 0,
  uncertain_count: 0,
  routine_count: 0,
  escalated_count: 0,
  analyzed_last_7_days: 0,
  vehicle_proximity_breaches: 0,
  total_feedback: 0,
  correct_feedback: 0,
  false_positive_feedback: 0,
  false_negative_feedback: 0,
};

beforeEach(() => {
  vi.clearAllMocks();
});

function mountView(isAdmin = true) {
  const pinia = makePinia();
  useAuthStore().user = { ...fakeUser, is_superuser: isAdmin };
  return mount(AiView, { global: mountGlobal(pinia, makeRouter()) });
}

describe("AiView loading", () => {
  it("shows a loading skeleton while fetching", () => {
    mockedStats.mockReturnValue(new Promise(() => {}));
    const wrapper = mountView();
    expect(wrapper.find('[data-testid="ai-loading"]').exists()).toBe(true);
  });

  it("shows a retry empty state when loading fails, and retry reloads", async () => {
    mockedStats.mockRejectedValueOnce(new ApiError(500, "Server exploded"));
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.find('[data-testid="ai-load-error"]').exists()).toBe(true);

    mockedStats.mockResolvedValueOnce(stats);
    await wrapper.find('[data-testid="retry-stats"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="ai-load-error"]').exists()).toBe(false);
    expect(wrapper.text()).toContain("Clips analyzed");
  });

  it("shows an empty state when nothing has been analyzed yet", async () => {
    mockedStats.mockResolvedValue(emptyStats);
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.find('[data-testid="ai-empty"]').exists()).toBe(true);
  });

  it("hides the AI settings shortcuts from a non-admin", async () => {
    mockedStats.mockResolvedValue(emptyStats);
    const wrapper = mountView(false);
    await flushPromises();
    expect(wrapper.find('[data-testid="go-ai-settings"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="go-ai-settings-empty"]').exists()).toBe(false);
  });

  it("links an admin to the AI Provider settings tab from the empty state", async () => {
    mockedStats.mockResolvedValue(emptyStats);
    const router = makeRouter();
    const pushSpy = vi.spyOn(router, "push");
    const pinia = makePinia();
    useAuthStore().user = { ...fakeUser, is_superuser: true };
    const wrapper = mount(AiView, { global: mountGlobal(pinia, router) });
    await flushPromises();
    await wrapper.find('[data-testid="go-ai-settings-empty"]').trigger("click");
    expect(pushSpy).toHaveBeenCalledWith({ name: "settings", query: { tab: "ai" } });
  });

  it("links an admin to the AI Provider settings tab from the page header", async () => {
    mockedStats.mockResolvedValue(stats);
    const router = makeRouter();
    const pushSpy = vi.spyOn(router, "push");
    const pinia = makePinia();
    useAuthStore().user = { ...fakeUser, is_superuser: true };
    const wrapper = mount(AiView, { global: mountGlobal(pinia, router) });
    await flushPromises();
    await wrapper.find('[data-testid="go-ai-settings"]').trigger("click");
    expect(pushSpy).toHaveBeenCalledWith({ name: "settings", query: { tab: "ai" } });
  });
});

describe("AiView populated", () => {
  beforeEach(() => {
    mockedStats.mockResolvedValue(stats);
  });

  it("renders activity tiles", async () => {
    const wrapper = mountView();
    await flushPromises();
    const text = wrapper.text();
    expect(text).toContain("40");
    expect(text).toContain("Clips analyzed");
    expect(text).toContain("12");
    expect(text).toContain("In the last 7 days");
    expect(text).toContain("8");
    expect(text).toContain("Escalated to Tier 2");
    expect(text).toContain("2");
    expect(text).toContain("Vehicle proximity breaches");
  });

  it("renders the suspicion breakdown with correct percentages", async () => {
    const wrapper = mountView();
    await flushPromises();
    const bar = wrapper.find('[data-testid="suspicion-bar"]');
    const segments = bar.findAll(".bar-segment");
    expect(segments[0]!.attributes("style")).toContain("width: 75%");
    expect(segments[1]!.attributes("style")).toContain("width: 15%");
    expect(segments[2]!.attributes("style")).toContain("width: 10%");
    expect(wrapper.text()).toContain("Routine — 30 (75%)");
    expect(wrapper.text()).toContain("Uncertain — 6 (15%)");
    expect(wrapper.text()).toContain("Suspicious — 4 (10%)");
  });

  it("renders feedback accuracy once feedback exists", async () => {
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.find('[data-testid="no-feedback"]').exists()).toBe(false);
    const text = wrapper.text();
    expect(text).toContain("80%");
    expect(text).toContain("Accuracy (10 rated)");
    expect(text).toContain("Confirmed correct");
    expect(text).toContain("False positives");
    expect(text).toContain("False negatives");
  });

  it("shows a no-feedback message when nothing has been rated yet", async () => {
    mockedStats.mockResolvedValue({ ...stats, total_feedback: 0 });
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.find('[data-testid="no-feedback"]').exists()).toBe(true);
  });

  it("falls back to a generic load error message for non-API failures", async () => {
    mockedStats.mockRejectedValue(new TypeError("down"));
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.find('[data-testid="ai-load-error"]').text()).toContain(
      "Couldn't load AI stats",
    );
  });
});
