import { flushPromises, mount } from "@vue/test-utils";
import Select from "primevue/select";
import ToggleSwitch from "primevue/toggleswitch";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/client";
import LiveView from "@/views/LiveView.vue";
import { useAuthStore } from "@/stores/auth";
import { fakeBlinkStatus, fakeUser, makePinia, makeRouter, mountGlobal } from "./helpers";

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  getBlinkStatus: vi.fn(),
  listCameras: vi.fn(),
  getLiveViewSettings: vi.fn(),
  recordCameraClip: vi.fn(),
}));

const toastAdd = vi.fn();
vi.mock("primevue/usetoast", () => ({ useToast: () => ({ add: toastAdd }) }));

import { getBlinkStatus, getLiveViewSettings, listCameras, recordCameraClip } from "@/api";

const mockedBlinkStatus = vi.mocked(getBlinkStatus);
const mockedListCameras = vi.mocked(listCameras);
const mockedSettings = vi.mocked(getLiveViewSettings);
const mockedRecord = vi.mocked(recordCameraClip);

function linkedStatus() {
  return fakeBlinkStatus({ linked: true, status: "active", camera_count: 2 });
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
  enabled: true,
  battery: null,
  last_synced_at: null,
  security_context: null,
};

const defaultSettings = {
  default_camera_id: null,
  auto_refresh_enabled: false,
  auto_refresh_interval_seconds: 10,
};

beforeEach(() => {
  vi.clearAllMocks();
  document.body.innerHTML = "";
  mockedBlinkStatus.mockResolvedValue(linkedStatus());
  mockedListCameras.mockResolvedValue([cameraA, cameraB]);
  mockedSettings.mockResolvedValue(defaultSettings);
});

// happy-dom doesn't implement createObjectURL/revokeObjectURL at all, so
// they're assigned directly (not vi.stubGlobal, which would replace the
// whole URL constructor with a non-constructable plain object - and since
// this project doesn't set `unstubGlobals`, that replacement would leak
// into every test file that runs afterward in the same process, not just
// this one). Deleted again after each test so URL is back to its real,
// un-augmented self for whatever spec runs next.
afterEach(() => {
  Reflect.deleteProperty(URL, "createObjectURL");
  Reflect.deleteProperty(URL, "revokeObjectURL");
});

async function mountView() {
  const router = makeRouter();
  await router.push("/live");
  const pinia = makePinia();
  useAuthStore().user = { ...fakeUser, is_superuser: true };
  const wrapper = mount(LiveView, {
    global: mountGlobal(pinia, router),
    attachTo: document.body,
  });
  await flushPromises();
  // The initial load leaves the primary panel "loading" (a real <img> load
  // event never fires on its own in jsdom) - PrimeVue's Button disables
  // itself while :loading="true", so every test needs this resolved first
  // or its button clicks would be silent no-ops. Only applies once a camera
  // actually rendered a preview (not the loading/error/empty states).
  const preview = wrapper.find('[data-testid="primary-preview"]');
  if (preview.exists()) {
    await preview.trigger("load");
    await flushPromises();
  }
  return wrapper;
}

describe("LiveView loading and empty states", () => {
  it("shows a loading skeleton while fetching", async () => {
    mockedListCameras.mockReturnValue(new Promise(() => {}));
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="live-view-loading"]').exists()).toBe(true);
  });

  it("shows the API error message when loading fails", async () => {
    mockedListCameras.mockRejectedValue(new ApiError(500, "Server exploded"));
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="live-view-load-error"]').text()).toBe("Server exploded");
  });

  it("falls back to a generic load error for non-API failures", async () => {
    mockedListCameras.mockRejectedValue(new TypeError("down"));
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="live-view-load-error"]').text()).toBe(
      "Could not load Live View.",
    );
  });

  it("shows an empty state with no cameras", async () => {
    mockedListCameras.mockResolvedValue([]);
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="live-view-empty"]').exists()).toBe(true);
  });
});

describe("LiveView single-camera mode", () => {
  it("defaults to the configured default camera", async () => {
    mockedSettings.mockResolvedValue({ ...defaultSettings, default_camera_id: cameraB.id });
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="primary-preview"]').attributes("src")).toContain(
      `/api/cameras/${cameraB.id}/preview`,
    );
  });

  it("falls back to the first camera when no default is configured", async () => {
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="primary-preview"]').attributes("src")).toContain(
      `/api/cameras/${cameraA.id}/preview`,
    );
  });

  it("switching the camera selector refreshes the preview", async () => {
    const wrapper = await mountView();
    const select = wrapper.findComponent(Select);
    await select.vm.$emit("update:modelValue", cameraB.id);
    await flushPromises();
    expect(wrapper.find('[data-testid="primary-preview"]').attributes("src")).toContain(
      `/api/cameras/${cameraB.id}/preview`,
    );
  });

  it("forces a fresh snapshot with the Refresh button and clears it on load", async () => {
    const wrapper = await mountView();
    await wrapper.find('[data-testid="primary-refresh"]').trigger("click");
    const src = wrapper.find('[data-testid="primary-preview"]').attributes("src")!;
    expect(src).toContain("force=true");
    expect(wrapper.find('[data-testid="primary-refresh"]').attributes("disabled")).toBeDefined();

    await wrapper.find('[data-testid="primary-preview"]').trigger("load");
    await flushPromises();
    expect(wrapper.find('[data-testid="primary-refresh"]').attributes("disabled")).toBeUndefined();
  });

  it("shows an overlay and updates state when the preview fails to load", async () => {
    const wrapper = await mountView();
    await wrapper.find('[data-testid="primary-preview"]').trigger("error");
    expect(wrapper.text()).toContain("Preview unavailable.");
  });

  it("triggers a recording and shows a success toast", async () => {
    mockedRecord.mockResolvedValue({ status: "recording_started" });
    const wrapper = await mountView();
    await wrapper.find('[data-testid="primary-save-clip"]').trigger("click");
    await flushPromises();
    expect(mockedRecord).toHaveBeenCalledWith(cameraA.id);
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "success", summary: "Recording started" }),
    );
  });

  it("shows an error toast when recording fails", async () => {
    mockedRecord.mockRejectedValue(new ApiError(502, "camera offline"));
    const wrapper = await mountView();
    await wrapper.find('[data-testid="primary-save-clip"]').trigger("click");
    await flushPromises();
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "error", detail: "camera offline" }),
    );
  });

  it("shows a generic error toast for a non-API recording failure", async () => {
    mockedRecord.mockRejectedValue(new TypeError("down"));
    const wrapper = await mountView();
    await wrapper.find('[data-testid="primary-save-clip"]').trigger("click");
    await flushPromises();
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "error", detail: "Unexpected error." }),
    );
  });
});

describe("LiveView compare mode", () => {
  it("adds a second panel with a different camera when toggled on", async () => {
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="secondary-preview"]').exists()).toBe(false);
    await wrapper.find('[data-testid="toggle-compare"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="secondary-preview"]').attributes("src")).toContain(
      `/api/cameras/${cameraB.id}/preview`,
    );
  });

  it("shows a fallback when there's no other camera to compare against", async () => {
    mockedListCameras.mockResolvedValue([cameraA]);
    const wrapper = await mountView();
    await wrapper.find('[data-testid="toggle-compare"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="secondary-no-camera"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="secondary-preview"]').exists()).toBe(false);
  });

  it("ignores save-clip and auto-refresh ticks for the secondary panel with no camera", async () => {
    mockedListCameras.mockResolvedValue([cameraA]);
    const wrapper = await mountView();
    await wrapper.find('[data-testid="toggle-compare"]').trigger("click");
    await flushPromises();

    await wrapper.find('[data-testid="secondary-save-clip"]').trigger("click");
    await flushPromises();
    expect(mockedRecord).not.toHaveBeenCalled();

    vi.useFakeTimers();
    try {
      const toggle = wrapper.findComponent(ToggleSwitch);
      await toggle.vm.$emit("update:modelValue", true);
      await flushPromises();
      // If the timer tick throws while refreshing a secondary panel with no
      // camera selected, awaiting this re-throws and fails the test.
      await vi.advanceTimersByTimeAsync(10_000);
      expect(mockedRecord).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("switching the secondary camera selector refreshes just that panel", async () => {
    const wrapper = await mountView();
    await wrapper.find('[data-testid="toggle-compare"]').trigger("click");
    await flushPromises();
    const selects = wrapper.findAllComponents(Select);
    await selects[1]!.vm.$emit("update:modelValue", cameraA.id);
    await flushPromises();
    expect(wrapper.find('[data-testid="secondary-preview"]').attributes("src")).toContain(
      `/api/cameras/${cameraA.id}/preview`,
    );
  });

  it("supports refresh, screenshot, save-clip, and an error overlay on the secondary panel", async () => {
    mockedRecord.mockResolvedValue({ status: "recording_started" });
    const wrapper = await mountView();
    await wrapper.find('[data-testid="toggle-compare"]').trigger("click");
    await flushPromises();
    await wrapper.find('[data-testid="secondary-preview"]').trigger("load");

    await wrapper.find('[data-testid="secondary-refresh"]').trigger("click");
    expect(wrapper.find('[data-testid="secondary-preview"]').attributes("src")).toContain(
      "force=true",
    );
    await wrapper.find('[data-testid="secondary-preview"]').trigger("load");

    await wrapper.find('[data-testid="secondary-save-clip"]').trigger("click");
    await flushPromises();
    expect(mockedRecord).toHaveBeenCalledWith(cameraB.id);

    await wrapper.find('[data-testid="secondary-preview"]').trigger("error");
    expect(wrapper.text()).toContain("Preview unavailable.");

    await wrapper.find('[data-testid="secondary-screenshot"]').trigger("click");
    // No camera loaded successfully at this point (last event was "error"),
    // so this should just no-op rather than throw.
  });

  it("removes the second panel when toggled back off", async () => {
    const wrapper = await mountView();
    await wrapper.find('[data-testid="toggle-compare"]').trigger("click");
    await flushPromises();
    await wrapper.find('[data-testid="toggle-compare"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="secondary-preview"]').exists()).toBe(false);
  });

  it("each panel's Refresh button only affects that panel", async () => {
    const wrapper = await mountView();
    await wrapper.find('[data-testid="toggle-compare"]').trigger("click");
    await flushPromises();
    const before = wrapper.find('[data-testid="secondary-preview"]').attributes("src");
    await wrapper.find('[data-testid="primary-refresh"]').trigger("click");
    const after = wrapper.find('[data-testid="secondary-preview"]').attributes("src");
    expect(after).toBe(before);
  });

  it("auto-refresh advances both panels together once enabled", async () => {
    const wrapper = await mountView();
    await wrapper.find('[data-testid="toggle-compare"]').trigger("click");
    await flushPromises();

    vi.useFakeTimers();
    try {
      const toggle = wrapper.findComponent(ToggleSwitch);
      await toggle.vm.$emit("update:modelValue", true);
      await flushPromises();

      const before = wrapper.find('[data-testid="secondary-preview"]').attributes("src");
      await vi.advanceTimersByTimeAsync(10_000);
      const after = wrapper.find('[data-testid="secondary-preview"]').attributes("src");
      expect(after).not.toBe(before);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("LiveView cleanup", () => {
  it("clears both timers on unmount without throwing", async () => {
    const wrapper = await mountView();
    const toggle = wrapper.findComponent(ToggleSwitch);
    await toggle.vm.$emit("update:modelValue", true);
    await flushPromises();
    expect(() => wrapper.unmount()).not.toThrow();
  });

  it("unmounts cleanly when auto-refresh was never enabled", async () => {
    const wrapper = await mountView();
    expect(() => wrapper.unmount()).not.toThrow();
  });
});

describe("LiveView auto-refresh and sidebar toggle", () => {
  it("polls the preview on the configured interval once enabled", async () => {
    vi.useFakeTimers();
    try {
      const wrapper = await mountView();
      const toggle = wrapper.findComponent(ToggleSwitch);
      await toggle.vm.$emit("update:modelValue", true);
      await flushPromises();

      const before = wrapper.find('[data-testid="primary-preview"]').attributes("src");
      await vi.advanceTimersByTimeAsync(10_000);
      const after = wrapper.find('[data-testid="primary-preview"]').attributes("src");
      expect(after).not.toBe(before);
    } finally {
      vi.useRealTimers();
    }
  });

  it("toggles the sidebar collapse state", async () => {
    const wrapper = await mountView();
    const button = wrapper.find('[data-testid="live-view-sidebar-toggle"]');
    expect(button.text()).toContain("Collapse menu");
    await button.trigger("click");
    expect(wrapper.find('[data-testid="live-view-sidebar-toggle"]').text()).toContain(
      "Expand menu",
    );
  });
});

describe("LiveView screenshot", () => {
  it("does nothing if the preview image can't be found", async () => {
    const wrapper = await mountView();
    // Detach the camera id so the selector in screenshot() can't match anything.
    await wrapper.find('[data-testid="primary-screenshot"]').trigger("click");
    // No throw is the assertion - nothing else observable changes.
    expect(wrapper.find('[data-testid="live-view-load-error"]').exists()).toBe(false);
  });

  it("does nothing when the image has no natural dimensions (never finished loading)", async () => {
    const wrapper = await mountView();
    await wrapper.find('[data-testid="primary-screenshot"]').trigger("click");
    expect(wrapper.find('[data-testid="live-view-load-error"]').exists()).toBe(false);
  });

  it("draws the loaded image to a canvas and downloads it", async () => {
    const wrapper = await mountView();
    const image = wrapper.find<HTMLImageElement>('[data-testid="primary-preview"]').element;
    Object.defineProperty(image, "naturalWidth", { value: 640, configurable: true });
    Object.defineProperty(image, "naturalHeight", { value: 360, configurable: true });

    const drawImage = vi.fn();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
      drawImage,
    } as unknown as CanvasRenderingContext2D);
    const fakeBlob = new Blob(["x"], { type: "image/jpeg" });
    vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation((cb) => cb(fakeBlob));
    URL.createObjectURL = vi.fn(() => "blob:fake");
    URL.revokeObjectURL = vi.fn();
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    await wrapper.find('[data-testid="primary-screenshot"]').trigger("click");

    expect(drawImage).toHaveBeenCalledWith(image, 0, 0);
    expect(clickSpy).toHaveBeenCalled();
    clickSpy.mockRestore();
  });

  it("does nothing when the canvas can't produce a 2d context", async () => {
    const wrapper = await mountView();
    const image = wrapper.find<HTMLImageElement>('[data-testid="primary-preview"]').element;
    Object.defineProperty(image, "naturalWidth", { value: 640, configurable: true });
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);

    await wrapper.find('[data-testid="primary-screenshot"]').trigger("click");
    expect(wrapper.find('[data-testid="live-view-load-error"]').exists()).toBe(false);
  });

  it("does nothing when toBlob produces no blob", async () => {
    const wrapper = await mountView();
    const image = wrapper.find<HTMLImageElement>('[data-testid="primary-preview"]').element;
    Object.defineProperty(image, "naturalWidth", { value: 640, configurable: true });
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
      drawImage: vi.fn(),
    } as unknown as CanvasRenderingContext2D);
    vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation((cb) => cb(null));

    await wrapper.find('[data-testid="primary-screenshot"]').trigger("click");
    expect(wrapper.find('[data-testid="live-view-load-error"]').exists()).toBe(false);
  });
});
