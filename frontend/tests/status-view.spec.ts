import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import StatusView from "@/views/StatusView.vue";
import {
  fakeBlinkStatus,
  fakeCamera,
  healthyReport,
  makePinia,
  makeRouter,
  mountGlobal,
} from "./helpers";

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  getHealth: vi.fn(),
  getBlinkStatus: vi.fn(),
  listCameras: vi.fn(),
  getCameraBatteryEvents: vi.fn(),
}));

import { getBlinkStatus, getCameraBatteryEvents, getHealth, listCameras } from "@/api";

const mockedHealth = vi.mocked(getHealth);
const mockedBlinkStatus = vi.mocked(getBlinkStatus);
const mockedListCameras = vi.mocked(listCameras);
const mockedGetBatteryEvents = vi.mocked(getCameraBatteryEvents);

const unlinkedStatus = fakeBlinkStatus();

const linkedStatus = fakeBlinkStatus({
  linked: true,
  status: "active",
  last_sync: "2026-07-26T12:00:00Z",
  camera_count: 3,
  network_ids: ["net-1"],
  total_clip_count: 42,
  daily_clip_counts: [
    { date: "2026-07-20", count: 1 },
    { date: "2026-07-21", count: 0 },
    { date: "2026-07-22", count: 2 },
    { date: "2026-07-23", count: 0 },
    { date: "2026-07-24", count: 3 },
    { date: "2026-07-25", count: 1 },
    { date: "2026-07-26", count: 5 },
  ],
});

beforeEach(() => {
  vi.clearAllMocks();
  mockedBlinkStatus.mockResolvedValue(unlinkedStatus);
  mockedListCameras.mockResolvedValue([]);
  mockedGetBatteryEvents.mockResolvedValue([]);
});

afterEach(() => {
  document.body.innerHTML = "";
});

function mountView() {
  return mount(StatusView, {
    global: mountGlobal(makePinia(), makeRouter()),
    attachTo: document.body,
  });
}

describe("StatusView platform health", () => {
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
    expect(mockedBlinkStatus).toHaveBeenCalledTimes(2);
  });
});

describe("StatusView Blink connection", () => {
  it("shows a skeleton while the first status check is in flight", async () => {
    mockedBlinkStatus.mockReturnValue(new Promise(() => undefined));
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.find('[data-testid="blink-loading"]').exists()).toBe(true);
  });

  it("shows a retry action when the status check fails", async () => {
    mockedBlinkStatus.mockRejectedValue(new TypeError("network down"));
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.find('[data-testid="blink-error"]').exists()).toBe(true);

    mockedBlinkStatus.mockResolvedValue(unlinkedStatus);
    await wrapper.find('[data-testid="retry-blink"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="connection-card"]').exists()).toBe(true);
  });

  it("shows a 'Not connected' state with a call to link an account", async () => {
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.find('[data-testid="connection-tag"]').text()).toBe("Not connected");
    expect(wrapper.text()).toContain("Link a Blink account");
    expect(wrapper.find('[data-testid="manage-blink"]').text()).toBe("Connect Blink account");
    expect(wrapper.find('[data-testid="connection-last-error"]').exists()).toBe(false);
  });

  it("shows the connected state with sync time, clip count, and camera count", async () => {
    mockedBlinkStatus.mockResolvedValue(linkedStatus);
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.find('[data-testid="connection-tag"]').text()).toBe("Connected");
    expect(wrapper.text()).toContain("Last synced");
    expect(wrapper.text()).toContain("42");
    expect(wrapper.text()).toContain("Total clips downloaded");
    expect(wrapper.text()).toContain("3");
    expect(wrapper.text()).toContain("Cameras");
    expect(wrapper.find('[data-testid="manage-blink"]').text()).toBe("Manage in Settings");
  });

  it("shows neither sync time nor link-prompt for a linked account with no sync yet", async () => {
    mockedBlinkStatus.mockResolvedValue({ ...linkedStatus, last_sync: null });
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.text()).not.toContain("Last synced");
    expect(wrapper.text()).not.toContain("Link a Blink account");
  });

  it("flags a linked account that needs attention, with its last error", async () => {
    mockedBlinkStatus.mockResolvedValue({
      ...linkedStatus,
      status: "error",
      last_error: "Blink rejected the stored credentials.",
    });
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.find('[data-testid="connection-tag"]').text()).toBe("Needs attention");
    expect(wrapper.find('[data-testid="connection-last-error"]').text()).toContain(
      "Blink rejected the stored credentials.",
    );
  });

  it("renders the 7-day trend chart from the daily clip counts", async () => {
    mockedBlinkStatus.mockResolvedValue(linkedStatus);
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.find('[data-testid="hit-6"]').exists()).toBe(true);
    await wrapper.find('[data-testid="hit-6"]').trigger("mouseenter");
    expect(wrapper.find('[data-testid="chart-tooltip"]').text()).toContain("5 clip(s)");
  });

  it("navigates to Settings when managing the Blink connection", async () => {
    const router = makeRouter();
    const pushSpy = vi.spyOn(router, "push");
    const wrapper = mount(StatusView, { global: mountGlobal(makePinia(), router) });
    await flushPromises();
    await wrapper.find('[data-testid="manage-blink"]').trigger("click");
    expect(pushSpy).toHaveBeenCalledWith({ name: "settings", query: { tab: "general" } });
  });

  it("shows the singular network ID label for one network", async () => {
    mockedBlinkStatus.mockResolvedValue(linkedStatus);
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.find('[data-testid="network-ids"]').text()).toBe("Network ID: net-1");
  });

  it("shows the plural network IDs label, comma-joined, for more than one network", async () => {
    mockedBlinkStatus.mockResolvedValue({ ...linkedStatus, network_ids: ["net-1", "net-2"] });
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.find('[data-testid="network-ids"]').text()).toBe(
      "Network IDs: net-1, net-2",
    );
  });

  it("hides the network ID line when there are none yet", async () => {
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.find('[data-testid="network-ids"]').exists()).toBe(false);
  });

  it("derives clips today from the last daily count and clips this week from their sum", async () => {
    mockedBlinkStatus.mockResolvedValue(linkedStatus);
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.find('[data-testid="clips-today"]').text()).toBe("5");
    expect(wrapper.find('[data-testid="clips-this-week"]').text()).toBe("12");
  });

  it("shows zero for today/this-week stats before any daily counts exist", async () => {
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.find('[data-testid="clips-today"]').text()).toBe("0");
    expect(wrapper.find('[data-testid="clips-this-week"]').text()).toBe("0");
  });
});

describe("StatusView cameras", () => {
  it("shows a loading skeleton while cameras are fetching", async () => {
    mockedListCameras.mockReturnValue(new Promise(() => undefined));
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.find('[data-testid="cameras-loading"]').exists()).toBe(true);
  });

  it("renders each camera's name, model, and battery status", async () => {
    mockedListCameras.mockResolvedValue([
      fakeCamera({ id: "cam-ok", name: "Front Door", battery: "ok" }),
      fakeCamera({ id: "cam-low", name: "Backyard", camera_type: "sonoran", battery: "low" }),
    ]);
    const wrapper = mountView();
    await flushPromises();

    const okTile = wrapper.find('[data-testid="camera-tile-cam-ok"]');
    expect(okTile.text()).toContain("Front Door");
    expect(okTile.text()).toContain("Blink Outdoor Gen 3");
    expect(okTile.text()).toContain("OK");

    const lowTile = wrapper.find('[data-testid="camera-tile-cam-low"]');
    expect(lowTile.text()).toContain("Backyard");
    expect(lowTile.text()).toContain("Low");
  });

  it("shows an empty state when no cameras exist", async () => {
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.find('[data-testid="cameras-empty"]').exists()).toBe(true);
  });

  it("shows a retry action when loading cameras fails", async () => {
    mockedListCameras.mockRejectedValue(new TypeError("network down"));
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.find('[data-testid="cameras-error"]').text()).toContain(
      "Could not load cameras.",
    );

    mockedListCameras.mockResolvedValue([fakeCamera()]);
    await wrapper.find('[data-testid="retry-cameras"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="cameras-empty"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid^="camera-tile-"]').exists()).toBe(true);
  });

  it("refetches cameras when Refresh is clicked", async () => {
    mockedListCameras.mockResolvedValue([]);
    const wrapper = mountView();
    await flushPromises();
    await wrapper.find('[data-testid="refresh"]').trigger("click");
    await flushPromises();
    expect(mockedListCameras).toHaveBeenCalledTimes(2);
  });

  it("opens the battery history dialog when a camera's battery badge is clicked", async () => {
    mockedListCameras.mockResolvedValue([fakeCamera({ id: "cam-ok", name: "Front Door" })]);
    const wrapper = mountView();
    await flushPromises();
    expect(document.body.querySelector('[data-testid="battery-history-dialog"]')).toBeFalsy();

    document.body.querySelector<HTMLElement>('[data-testid="camera-battery-cam-ok"]')?.click();
    await flushPromises();

    const dialog = document.body.querySelector('[data-testid="battery-history-dialog"]');
    expect(dialog).toBeTruthy();
    expect(dialog?.textContent).toContain("Front Door");
    expect(mockedGetBatteryEvents).toHaveBeenCalledWith("cam-ok");

    await wrapper.findComponent({ name: "Dialog" }).vm.$emit("update:visible", false);
    await flushPromises();
    expect(document.body.querySelector('[data-testid="battery-history-dialog"]')).toBeFalsy();
  });
});
