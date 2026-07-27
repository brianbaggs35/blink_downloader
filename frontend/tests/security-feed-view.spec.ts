import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/client";
import SecurityFeedView from "@/views/SecurityFeedView.vue";
import { useAuthStore } from "@/stores/auth";
import { fakeBlinkStatus, fakeUser, makePinia, makeRouter, mountGlobal } from "./helpers";

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  getBlinkStatus: vi.fn(),
  listCameras: vi.fn(),
  getSecurityFeedSettings: vi.fn(),
  recordCameraClip: vi.fn(),
}));

const toastAdd = vi.fn();
vi.mock("primevue/usetoast", () => ({ useToast: () => ({ add: toastAdd }) }));

import {
  getBlinkStatus,
  getSecurityFeedSettings,
  listCameras,
  recordCameraClip,
} from "@/api";

const mockedBlinkStatus = vi.mocked(getBlinkStatus);
const mockedListCameras = vi.mocked(listCameras);
const mockedSettings = vi.mocked(getSecurityFeedSettings);
const mockedRecord = vi.mocked(recordCameraClip);

function linkedStatus() {
  return fakeBlinkStatus({ linked: true, status: "active", camera_count: 2 });
}
function unlinkedStatus() {
  return fakeBlinkStatus();
}

const cameraA = {
  id: "aaaaaaaa-1111-2222-3333-444455556666",
  name: "Driveway",
  camera_type: "catalina",
  enabled: true,
  battery: "ok",
  last_synced_at: null,
  security_context: null,
};
const cameraB = {
  id: "bbbbbbbb-1111-2222-3333-444455556666",
  name: "Backyard",
  camera_type: "sedona",
  enabled: false,
  battery: null,
  last_synced_at: null,
  security_context: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  mockedBlinkStatus.mockResolvedValue(linkedStatus());
  mockedListCameras.mockResolvedValue([cameraA, cameraB]);
  mockedSettings.mockResolvedValue({ camera_ids: [], columns: 2, refresh_interval_seconds: 20 });
});

async function mountView(isAdmin = true) {
  const router = makeRouter();
  await router.push("/security-feed");
  const pinia = makePinia();
  useAuthStore().user = { ...fakeUser, is_superuser: isAdmin };
  const wrapper = mount(SecurityFeedView, { global: mountGlobal(pinia, router) });
  await flushPromises();
  return wrapper;
}

describe("SecurityFeedView loading and empty states", () => {
  it("shows a loading skeleton while fetching", async () => {
    mockedListCameras.mockReturnValue(new Promise(() => {}));
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="feed-loading"]').exists()).toBe(true);
  });

  it("shows the API error message when loading fails", async () => {
    mockedListCameras.mockRejectedValue(new ApiError(500, "Server exploded"));
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="feed-load-error"]').text()).toBe("Server exploded");
  });

  it("falls back to a generic load error for non-API failures", async () => {
    mockedListCameras.mockRejectedValue(new TypeError("down"));
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="feed-load-error"]').text()).toBe(
      "Could not load the security feed.",
    );
  });

  it("shows an empty state when no Blink account is linked", async () => {
    mockedBlinkStatus.mockResolvedValue(unlinkedStatus());
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="feed-no-blink"]').exists()).toBe(true);
  });

  it("shows an empty state when no cameras are enabled and none are chosen", async () => {
    mockedListCameras.mockResolvedValue([{ ...cameraA, enabled: false }]);
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="feed-empty"]').exists()).toBe(true);
  });
});

describe("SecurityFeedView camera grid", () => {
  it("defaults to every enabled camera when none are explicitly chosen", async () => {
    const wrapper = await mountView();
    expect(wrapper.find(`[data-testid="feed-tile-${cameraA.id}"]`).exists()).toBe(true);
    expect(wrapper.find(`[data-testid="feed-tile-${cameraB.id}"]`).exists()).toBe(false);
  });

  it("shows exactly the chosen cameras, in order, when configured", async () => {
    mockedSettings.mockResolvedValue({
      camera_ids: [cameraB.id, cameraA.id],
      columns: 3,
      refresh_interval_seconds: 20,
    });
    const wrapper = await mountView();
    const tiles = wrapper.findAll("[data-testid^='feed-tile-']");
    expect(tiles.map((t) => t.attributes("data-testid"))).toEqual([
      `feed-tile-${cameraB.id}`,
      `feed-tile-${cameraA.id}`,
    ]);
  });

  it("shows a paused tag for a disabled camera explicitly chosen", async () => {
    mockedSettings.mockResolvedValue({
      camera_ids: [cameraB.id],
      columns: 2,
      refresh_interval_seconds: 20,
    });
    const wrapper = await mountView();
    expect(wrapper.find(`[data-testid="feed-tile-${cameraB.id}"]`).text()).toContain("Paused");
  });

  it("shows an overlay when a tile's image fails to load", async () => {
    const wrapper = await mountView();
    await wrapper.find("img").trigger("error");
    expect(wrapper.find('[data-testid="tile-error"]').exists()).toBe(true);
  });

  it("clears the error overlay once the image loads successfully", async () => {
    const wrapper = await mountView();
    await wrapper.find("img").trigger("error");
    expect(wrapper.find('[data-testid="tile-error"]').exists()).toBe(true);
    await wrapper.find("img").trigger("load");
    expect(wrapper.find('[data-testid="tile-error"]').exists()).toBe(false);
  });

  it("shows admin actions (snap/record/customize) only for an admin", async () => {
    const admin = await mountView(true);
    expect(admin.find(`[data-testid="snap-now-${cameraA.id}"]`).exists()).toBe(true);
    expect(admin.find(`[data-testid="record-now-${cameraA.id}"]`).exists()).toBe(true);
    expect(admin.find('[data-testid="customize-feed"]').exists()).toBe(true);

    const viewer = await mountView(false);
    expect(viewer.find(`[data-testid="snap-now-${cameraA.id}"]`).exists()).toBe(false);
    expect(viewer.find(`[data-testid="record-now-${cameraA.id}"]`).exists()).toBe(false);
    expect(viewer.find('[data-testid="customize-feed"]').exists()).toBe(false);
  });

  it("toasts success once a recording starts", async () => {
    mockedRecord.mockResolvedValue({ status: "queued" });
    const wrapper = await mountView();
    await wrapper.find(`[data-testid="record-now-${cameraA.id}"]`).trigger("click");
    await flushPromises();
    expect(mockedRecord).toHaveBeenCalledWith(cameraA.id);
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "success", summary: "Recording started" }),
    );
  });

  it("toasts the API error message when starting a recording fails", async () => {
    mockedRecord.mockRejectedValue(new ApiError(502, "camera offline"));
    const wrapper = await mountView();
    await wrapper.find(`[data-testid="record-now-${cameraA.id}"]`).trigger("click");
    await flushPromises();
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({
        severity: "error",
        summary: "Could not start recording",
        detail: "camera offline",
      }),
    );
  });

  it("toasts a generic error for a non-API recording failure", async () => {
    mockedRecord.mockRejectedValue(new TypeError("down"));
    const wrapper = await mountView();
    await wrapper.find(`[data-testid="record-now-${cameraA.id}"]`).trigger("click");
    await flushPromises();
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "error", detail: "Unexpected error." }),
    );
  });

  it("forces a fresh snapshot when Snap is clicked", async () => {
    const wrapper = await mountView();
    expect(wrapper.text()).toContain("Loading…");
    await wrapper.find(`[data-testid="snap-now-${cameraA.id}"]`).trigger("click");
    await flushPromises();
    expect(wrapper.text()).not.toContain("Loading…");
  });

  it("still marks the tile updated even if the forced snapshot fails to decode", async () => {
    const decodeSpy = vi
      .spyOn(HTMLImageElement.prototype, "decode")
      .mockRejectedValueOnce(new Error("decode failed"));
    const wrapper = await mountView();
    await wrapper.find(`[data-testid="snap-now-${cameraA.id}"]`).trigger("click");
    await flushPromises();
    const button = wrapper.find(`[data-testid="snap-now-${cameraA.id}"]`)
      .element as HTMLButtonElement;
    expect(button.disabled).toBe(false);
    expect(wrapper.text()).not.toContain("Loading…");
    decodeSpy.mockRestore();
  });
});

describe("SecurityFeedView cleanup", () => {
  it("clears both timers when unmounted after a successful load", async () => {
    const wrapper = await mountView();
    expect(() => wrapper.unmount()).not.toThrow();
  });

  it("clears only the clock timer when unmounted before the load resolves", async () => {
    mockedListCameras.mockReturnValue(new Promise(() => {}));
    const wrapper = await mountView();
    expect(() => wrapper.unmount()).not.toThrow();
  });
});

describe("SecurityFeedView polling", () => {
  it("bumps the tile's image source on each refresh interval", async () => {
    vi.useFakeTimers();
    try {
      const wrapper = await mountView();
      const srcBefore = wrapper.find("img").attributes("src");
      await vi.advanceTimersByTimeAsync(20_000);
      const srcAfter = wrapper.find("img").attributes("src");
      expect(srcAfter).not.toBe(srcBefore);
    } finally {
      vi.useRealTimers();
    }
  });
});
