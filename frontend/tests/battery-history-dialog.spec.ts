import { flushPromises, mount } from "@vue/test-utils";
import Dialog from "primevue/dialog";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  getCameraBatteryEvents: vi.fn(),
}));

import { ApiError, getCameraBatteryEvents } from "@/api";
import BatteryHistoryDialog from "@/components/BatteryHistoryDialog.vue";
import { makePinia, mountGlobal } from "./helpers";

import type { BatteryEventRead, CameraRead } from "@/api";

const mockedGetEvents = vi.mocked(getCameraBatteryEvents);

const camera: CameraRead = {
  id: "cam-1",
  name: "Backyard",
  camera_type: "catalina",
  enabled: true,
  battery: "low",
  last_synced_at: "2026-08-01T12:00:00Z",
  security_context: null,
};

const events: BatteryEventRead[] = [
  {
    id: "evt-2",
    battery: "low",
    previous_battery: "ok",
    occurred_at: "2026-08-03T14:00:00Z",
  },
  {
    id: "evt-1",
    battery: "ok",
    previous_battery: null,
    occurred_at: "2026-07-28T09:00:00Z",
  },
];

function mountDialog(initialCamera: CameraRead | null = camera) {
  return mount(BatteryHistoryDialog, {
    props: { camera: initialCamera },
    global: mountGlobal(makePinia()),
    attachTo: document.body,
  });
}

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("BatteryHistoryDialog", () => {
  it("stays closed and fetches nothing when no camera is selected", async () => {
    mountDialog(null);
    await flushPromises();
    expect(mockedGetEvents).not.toHaveBeenCalled();
    expect(document.body.querySelector('[data-testid="battery-history-dialog"]')).toBeFalsy();
  });

  it("shows a loading skeleton while fetching", async () => {
    mockedGetEvents.mockReturnValue(new Promise(() => {}));
    mountDialog();
    await flushPromises();
    expect(document.body.querySelector('[data-testid="battery-history-loading"]')).toBeTruthy();
  });

  it("renders the timeline and activity list once loaded", async () => {
    mockedGetEvents.mockResolvedValue(events);
    mountDialog();
    await flushPromises();

    expect(document.body.textContent).toContain("Backyard");

    const segments = document.body.querySelectorAll(
      '[data-testid="battery-timeline"] > div[class*="timeline-segment"]',
    );
    expect(segments).toHaveLength(2);

    const activityRows = document.body.querySelectorAll('[data-testid="battery-activity-list"] li');
    expect(activityRows).toHaveLength(2);
    expect(activityRows[0]?.textContent).toContain("Low");
  });

  it("shows an empty state when the camera has no recorded events", async () => {
    mockedGetEvents.mockResolvedValue([]);
    mountDialog();
    await flushPromises();
    expect(document.body.querySelector('[data-testid="battery-history-empty"]')).toBeTruthy();
  });

  it("shows an ApiError's message on failure", async () => {
    mockedGetEvents.mockRejectedValue(new ApiError(404, "Camera not found."));
    mountDialog();
    await flushPromises();
    expect(document.body.textContent).toContain("Camera not found.");
  });

  it("falls back to a generic message for a non-ApiError failure", async () => {
    mockedGetEvents.mockRejectedValue(new Error("network down"));
    mountDialog();
    await flushPromises();
    expect(document.body.textContent).toContain("Could not load battery history.");
  });

  it("refetches when the selected camera changes", async () => {
    mockedGetEvents.mockResolvedValue([]);
    const wrapper = mountDialog(camera);
    await flushPromises();
    expect(mockedGetEvents).toHaveBeenCalledWith("cam-1");

    await wrapper.setProps({ camera: { ...camera, id: "cam-2", name: "Front Door" } });
    await flushPromises();
    expect(mockedGetEvents).toHaveBeenCalledWith("cam-2");
  });

  it("emits close when the dialog's visibility is set to false", async () => {
    mockedGetEvents.mockResolvedValue([]);
    const wrapper = mountDialog();
    await flushPromises();
    await wrapper.findComponent(Dialog).vm.$emit("update:visible", false);
    expect(wrapper.emitted("close")).toHaveLength(1);
  });

  it("does not emit close when the dialog's visibility is set to true", async () => {
    mockedGetEvents.mockResolvedValue([]);
    const wrapper = mountDialog();
    await flushPromises();
    await wrapper.findComponent(Dialog).vm.$emit("update:visible", true);
    expect(wrapper.emitted("close")).toBeUndefined();
  });

  it("omits the inline label on a segment too narrow to comfortably fit it", async () => {
    const now = new Date();
    const barelyAMinuteAgo = new Date(now.getTime() - 60_000).toISOString();
    const monthsAgo = new Date(now.getTime() - 90 * 24 * 60 * 60 * 1000).toISOString();
    mockedGetEvents.mockResolvedValue([
      { id: "evt-recent", battery: "low", previous_battery: "ok", occurred_at: barelyAMinuteAgo },
      { id: "evt-old", battery: "ok", previous_battery: null, occurred_at: monthsAgo },
    ]);
    mountDialog();
    await flushPromises();

    const segments = document.body.querySelectorAll(
      '[data-testid="battery-timeline"] > div[class*="timeline-segment"]',
    );
    expect(segments).toHaveLength(2);
    // The "low" segment spans only the last minute of a ~3-month timeline -
    // nowhere near the 15% width floor, so it renders with no inline label.
    const narrowSegment = [...segments].find((el) => el.className.includes("--low"));
    expect(narrowSegment?.querySelector(".timeline-segment-label")).toBeFalsy();
  });
});
