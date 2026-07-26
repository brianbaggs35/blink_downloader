import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

import StatusView from "@/views/StatusView.vue";
import { healthyReport, makePinia, mountGlobal } from "./helpers";

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  getHealth: vi.fn(),
}));

import { beforeEach } from "vitest";

import { getHealth } from "@/api";

const mockedHealth = vi.mocked(getHealth);

beforeEach(() => {
  vi.clearAllMocks();
});

function mountView() {
  return mount(StatusView, { global: mountGlobal(makePinia()) });
}

describe("StatusView", () => {
  it("shows skeletons while loading", async () => {
    mockedHealth.mockReturnValue(new Promise(() => undefined));
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.find('[data-testid="loading"]').exists()).toBe(true);
  });

  it("renders healthy tiles with icon and label", async () => {
    mockedHealth.mockResolvedValue(healthyReport);
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.find('[data-testid="tile-api"]').text()).toContain("Operational · v1.0.0");
    expect(wrapper.find('[data-testid="tile-database"]').text()).toContain("Operational");
    expect(wrapper.find('[data-testid="tile-database"] i.pi-check-circle').exists()).toBe(true);
    expect(wrapper.find('[data-testid="tile-worker"]').classes()).toContain("state-ok");
  });

  it("marks failing components and unknown worker state", async () => {
    mockedHealth.mockResolvedValue({
      ...healthyReport,
      status: "degraded",
      database: "error",
      worker: "unknown",
    });
    const wrapper = mountView();
    await flushPromises();
    const db = wrapper.find('[data-testid="tile-database"]');
    expect(db.classes()).toContain("state-error");
    expect(db.text()).toContain("Unavailable");
    expect(db.find("i.pi-times-circle").exists()).toBe(true);
    const worker = wrapper.find('[data-testid="tile-worker"]');
    expect(worker.text()).toContain("Unknown");
    expect(worker.find("i.pi-question-circle").exists()).toBe(true);
  });

  it("reports an unreachable API", async () => {
    mockedHealth.mockRejectedValue(new TypeError("fetch failed"));
    const wrapper = mountView();
    await flushPromises();
    const api = wrapper.find('[data-testid="tile-api"]');
    expect(api.classes()).toContain("state-error");
    expect(api.text()).toContain("Unreachable");
    expect(wrapper.find('[data-testid="tile-database"]').text()).toContain("Unknown");
  });

  it("refreshes on demand", async () => {
    mockedHealth.mockResolvedValue(healthyReport);
    const wrapper = mountView();
    await flushPromises();
    await wrapper.find('[data-testid="refresh"]').trigger("click");
    await flushPromises();
    expect(mockedHealth).toHaveBeenCalledTimes(2);
  });
});
