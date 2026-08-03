import { flushPromises, mount } from "@vue/test-utils";
import ToggleSwitch from "primevue/toggleswitch";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  listSyncModules: vi.fn(),
  listSyncModuleCameras: vi.fn(),
  armSyncModule: vi.fn(),
  setCameraMotionDetection: vi.fn(),
  bulkSetCameraMotionDetection: vi.fn(),
}));

const toastAdd = vi.fn();
vi.mock("primevue/usetoast", () => ({ useToast: () => ({ add: toastAdd }) }));

import {
  armSyncModule,
  bulkSetCameraMotionDetection,
  listSyncModuleCameras,
  listSyncModules,
  setCameraMotionDetection,
} from "@/api";
import { ApiError } from "@/api/client";
import { useAuthStore } from "@/stores/auth";
import SyncModuleView from "@/views/SyncModuleView.vue";
import { fakeUser, makePinia, makeRouter, mountGlobal } from "./helpers";

const mockedSyncModules = vi.mocked(listSyncModules);
const mockedCameras = vi.mocked(listSyncModuleCameras);
const mockedArm = vi.mocked(armSyncModule);
const mockedSetMotion = vi.mocked(setCameraMotionDetection);
const mockedBulkMotion = vi.mocked(bulkSetCameraMotionDetection);

const HUB_ID = "ssssssss-1111-2222-3333-444455556666";
const OWL_ID = "oooooooo-1111-2222-3333-444455556666";

function hubFixture(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: HUB_ID,
    network_id: "net-1",
    name: "Home",
    serial: "SN-0001",
    firmware_version: "2.14.28",
    is_physical_hub: true,
    armed: true,
    online: true,
    local_storage_compatible: true,
    local_storage_enabled: true,
    local_storage_active: true,
    local_storage_status: "idle" as const,
    local_storage_manifest_refreshed_at: "2026-07-29T01:00:00Z",
    local_storage_last_error: null,
    camera_count: 2,
    last_synced_at: "2026-07-29T01:00:00Z",
    ...overrides,
  };
}

const cameraDefault = {
  camera_id: "cccccccc-1111-2222-3333-444455556666",
  name: "Front Door",
  camera_type: "catalina",
  motion_enabled: true,
  motion_supported: true,
  battery: "ok",
};

const cameraMini = {
  camera_id: "dddddddd-1111-2222-3333-444455556666",
  name: "Backyard Mini",
  camera_type: "owl",
  motion_enabled: true,
  motion_supported: false,
  battery: null,
};

beforeEach(() => {
  vi.clearAllMocks();
});

function mountView(isAdmin = true) {
  const pinia = makePinia();
  useAuthStore().user = { ...fakeUser, is_superuser: isAdmin };
  return mount(SyncModuleView, {
    global: {
      ...mountGlobal(pinia, makeRouter()),
      stubs: { SyncModuleLocalStorageBrowser: true },
    },
  });
}

describe("SyncModuleView loading", () => {
  it("shows a loading skeleton while fetching", () => {
    mockedSyncModules.mockReturnValue(new Promise(() => {}));
    const wrapper = mountView();
    expect(wrapper.find('[data-testid="sync-modules-loading"]').exists()).toBe(true);
  });

  it("shows the API error message when loading fails, and retry reloads", async () => {
    mockedSyncModules.mockRejectedValueOnce(new ApiError(500, "Server exploded"));
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.find('[data-testid="sync-modules-load-error"]').exists()).toBe(true);

    mockedSyncModules.mockResolvedValueOnce([]);
    await wrapper.find('[data-testid="retry-sync-modules"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="sync-modules-load-error"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="sync-modules-empty"]').exists()).toBe(true);
  });

  it("falls back to a generic load error for non-API failures", async () => {
    mockedSyncModules.mockRejectedValue(new TypeError("down"));
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.find('[data-testid="sync-modules-load-error"]').text()).toContain(
      "Couldn't load Sync Modules",
    );
  });

  it("shows an empty state when there are none", async () => {
    mockedSyncModules.mockResolvedValue([]);
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.find('[data-testid="sync-modules-empty"]').exists()).toBe(true);
  });
});

describe("SyncModuleView identity", () => {
  it("renders name, online tag, serial, and firmware", async () => {
    mockedSyncModules.mockResolvedValue([hubFixture()]);
    mockedCameras.mockResolvedValue([]);
    const wrapper = mountView();
    await flushPromises();
    const card = wrapper.find(`[data-testid="sync-module-card-${HUB_ID}"]`);
    expect(card.text()).toContain("Home");
    expect(card.text()).toContain("Online");
    expect(card.text()).toContain("SN-0001");
    expect(card.text()).toContain("2.14.28");
  });

  it("omits the serial/firmware line entirely when neither is reported", async () => {
    mockedSyncModules.mockResolvedValue([hubFixture({ serial: null, firmware_version: null })]);
    mockedCameras.mockResolvedValue([]);
    const wrapper = mountView();
    await flushPromises();
    const card = wrapper.find(`[data-testid="sync-module-card-${HUB_ID}"]`);
    expect(card.text()).not.toContain("Serial:");
    expect(card.text()).not.toContain("Firmware:");
  });

  it("shows Offline and a 'No physical hub' tag for a sync-less network", async () => {
    mockedSyncModules.mockResolvedValue([
      hubFixture({ id: OWL_ID, is_physical_hub: false, online: false, local_storage_compatible: false }),
    ]);
    mockedCameras.mockResolvedValue([]);
    const wrapper = mountView();
    await flushPromises();
    const card = wrapper.find(`[data-testid="sync-module-card-${OWL_ID}"]`);
    expect(card.text()).toContain("Offline");
    expect(card.text()).toContain("No physical hub");
  });
});

describe("SyncModuleView arm/disarm", () => {
  it("shows the current armed state and lets an admin disarm it", async () => {
    mockedSyncModules.mockResolvedValue([hubFixture({ armed: true })]);
    mockedCameras.mockResolvedValue([]);
    mockedArm.mockResolvedValue(hubFixture({ armed: false }));
    const wrapper = mountView();
    await flushPromises();

    expect(wrapper.find(`[data-testid="arm-state-${HUB_ID}"]`).text()).toBe("Armed");
    await wrapper.find(`[data-testid="arm-toggle-${HUB_ID}"]`).trigger("click");
    await flushPromises();

    expect(mockedArm).toHaveBeenCalledWith(HUB_ID, false);
    expect(wrapper.find(`[data-testid="arm-state-${HUB_ID}"]`).text()).toBe("Disarmed");
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "success", summary: "Home disarmed" }),
    );
  });

  it("shows Unknown for a null armed state, and arms on click (never coerced to false)", async () => {
    mockedSyncModules.mockResolvedValue([hubFixture({ armed: null })]);
    mockedCameras.mockResolvedValue([]);
    mockedArm.mockResolvedValue(hubFixture({ armed: true }));
    const wrapper = mountView();
    await flushPromises();

    expect(wrapper.find(`[data-testid="arm-state-${HUB_ID}"]`).text()).toBe("Unknown");
    expect(wrapper.find(`[data-testid="arm-toggle-${HUB_ID}"]`).text()).toBe("Arm");
    await wrapper.find(`[data-testid="arm-toggle-${HUB_ID}"]`).trigger("click");
    await flushPromises();
    expect(mockedArm).toHaveBeenCalledWith(HUB_ID, true);
  });

  it("toasts an API error message when arming fails", async () => {
    mockedSyncModules.mockResolvedValue([hubFixture()]);
    mockedCameras.mockResolvedValue([]);
    mockedArm.mockRejectedValue(new ApiError(502, "Sync Module offline."));
    const wrapper = mountView();
    await flushPromises();

    await wrapper.find(`[data-testid="arm-toggle-${HUB_ID}"]`).trigger("click");
    await flushPromises();
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "error", detail: "Sync Module offline." }),
    );
  });

  it("toasts a generic error for a non-API arming failure", async () => {
    mockedSyncModules.mockResolvedValue([hubFixture()]);
    mockedCameras.mockResolvedValue([]);
    mockedArm.mockRejectedValue(new TypeError("down"));
    const wrapper = mountView();
    await flushPromises();

    await wrapper.find(`[data-testid="arm-toggle-${HUB_ID}"]`).trigger("click");
    await flushPromises();
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "error", detail: "Unexpected error." }),
    );
  });

  it("hides the arm/disarm button for a non-admin", async () => {
    mockedSyncModules.mockResolvedValue([hubFixture()]);
    mockedCameras.mockResolvedValue([]);
    const wrapper = mountView(false);
    await flushPromises();
    expect(wrapper.find(`[data-testid="arm-toggle-${HUB_ID}"]`).exists()).toBe(false);
    expect(wrapper.find(`[data-testid="arm-state-${HUB_ID}"]`).text()).toBe("Armed");
  });
});

describe("SyncModuleView per-camera motion", () => {
  it("shows a per-sync-module cameras loading skeleton", () => {
    mockedSyncModules.mockResolvedValue([hubFixture()]);
    mockedCameras.mockReturnValue(new Promise(() => {}));
    const wrapper = mountView();
    return flushPromises().then(() => {
      expect(wrapper.find(`[data-testid="cameras-loading-${HUB_ID}"]`).exists()).toBe(true);
    });
  });

  it("shows a per-sync-module cameras load error", async () => {
    mockedSyncModules.mockResolvedValue([hubFixture()]);
    mockedCameras.mockRejectedValue(new ApiError(500, "Server exploded"));
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.find(`[data-testid="cameras-error-${HUB_ID}"]`).text()).toBe("Server exploded");
  });

  it("falls back to a generic per-sync-module cameras load error", async () => {
    mockedSyncModules.mockResolvedValue([hubFixture()]);
    mockedCameras.mockRejectedValue(new TypeError("down"));
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.find(`[data-testid="cameras-error-${HUB_ID}"]`).text()).toBe(
      "Could not load cameras.",
    );
  });

  it("shows an empty message when the network has no cameras yet", async () => {
    mockedSyncModules.mockResolvedValue([hubFixture()]);
    mockedCameras.mockResolvedValue([]);
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.find(`[data-testid="cameras-empty-${HUB_ID}"]`).exists()).toBe(true);
  });

  it("toggles an individual camera's motion detection and updates the row", async () => {
    mockedSyncModules.mockResolvedValue([hubFixture()]);
    mockedCameras.mockResolvedValue([cameraDefault]);
    mockedSetMotion.mockResolvedValue({ ...cameraDefault, motion_enabled: false });
    const wrapper = mountView();
    await flushPromises();

    const toggles = wrapper.findAllComponents(ToggleSwitch);
    await toggles[0]!.vm.$emit("update:modelValue", false);
    await flushPromises();

    expect(mockedSetMotion).toHaveBeenCalledWith(HUB_ID, cameraDefault.camera_id, false);
    const row = wrapper.find(`[data-testid="camera-motion-row-${cameraDefault.camera_id}"]`);
    expect(row.text()).toContain("Front Door");
    // camera_type "catalina" is translated to its real hardware name -
    // see frontend/src/lib/cameraModels.ts.
    expect(row.text()).toContain("Blink Outdoor Gen 3");
  });

  it("toasts an error when toggling an individual camera fails", async () => {
    mockedSyncModules.mockResolvedValue([hubFixture()]);
    mockedCameras.mockResolvedValue([cameraDefault]);
    mockedSetMotion.mockRejectedValue(new ApiError(409, "Mini cameras don't support this."));
    const wrapper = mountView();
    await flushPromises();

    const toggles = wrapper.findAllComponents(ToggleSwitch);
    await toggles[0]!.vm.$emit("update:modelValue", false);
    await flushPromises();

    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "error", detail: "Mini cameras don't support this." }),
    );
  });

  it("toasts a generic error for a non-API individual toggle failure", async () => {
    mockedSyncModules.mockResolvedValue([hubFixture()]);
    mockedCameras.mockResolvedValue([cameraDefault]);
    mockedSetMotion.mockRejectedValue(new TypeError("down"));
    const wrapper = mountView();
    await flushPromises();

    const toggles = wrapper.findAllComponents(ToggleSwitch);
    await toggles[0]!.vm.$emit("update:modelValue", false);
    await flushPromises();

    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "error", detail: "Unexpected error." }),
    );
  });

  it("disables the toggle for a Mini and shows a read-only tag for a non-admin", async () => {
    mockedSyncModules.mockResolvedValue([hubFixture()]);
    mockedCameras.mockResolvedValue([cameraMini]);
    const wrapper = mountView();
    await flushPromises();

    const toggle = wrapper.findComponent(ToggleSwitch);
    expect(toggle.props("disabled")).toBe(true);
  });

  it("shows a read-only motion tag instead of a toggle for a non-admin", async () => {
    mockedSyncModules.mockResolvedValue([hubFixture()]);
    mockedCameras.mockResolvedValue([cameraDefault]);
    const wrapper = mountView(false);
    await flushPromises();
    expect(wrapper.findComponent(ToggleSwitch).exists()).toBe(false);
    expect(
      wrapper.find(`[data-testid="camera-motion-row-${cameraDefault.camera_id}"]`).text(),
    ).toContain("Motion on");
  });

  it("shows Motion off for a disabled camera's read-only tag", async () => {
    mockedSyncModules.mockResolvedValue([hubFixture()]);
    mockedCameras.mockResolvedValue([{ ...cameraDefault, motion_enabled: false }]);
    const wrapper = mountView(false);
    await flushPromises();
    expect(
      wrapper.find(`[data-testid="camera-motion-row-${cameraDefault.camera_id}"]`).text(),
    ).toContain("Motion off");
  });
});

describe("SyncModuleView bulk motion", () => {
  it("enables motion for all cameras and shows a success toast", async () => {
    mockedSyncModules.mockResolvedValue([hubFixture()]);
    mockedCameras.mockResolvedValue([cameraDefault]);
    mockedBulkMotion.mockResolvedValue({ succeeded: 1, failed: 0 });
    const wrapper = mountView();
    await flushPromises();

    await wrapper.find(`[data-testid="motion-enable-all-${HUB_ID}"]`).trigger("click");
    await flushPromises();

    expect(mockedBulkMotion).toHaveBeenCalledWith(HUB_ID, true);
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "success", summary: "Enabled motion on 1 camera(s)" }),
    );
  });

  it("disables motion for all cameras and warns when some fail", async () => {
    mockedSyncModules.mockResolvedValue([hubFixture()]);
    mockedCameras.mockResolvedValue([cameraDefault]);
    mockedBulkMotion.mockResolvedValue({ succeeded: 1, failed: 1 });
    const wrapper = mountView();
    await flushPromises();

    await wrapper.find(`[data-testid="motion-disable-all-${HUB_ID}"]`).trigger("click");
    await flushPromises();

    expect(mockedBulkMotion).toHaveBeenCalledWith(HUB_ID, false);
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({
        severity: "warn",
        summary: "Disabled motion on 1 camera(s)",
        detail: "1 could not be updated.",
      }),
    );
  });

  it("toasts an API error when the bulk action fails outright", async () => {
    mockedSyncModules.mockResolvedValue([hubFixture()]);
    mockedCameras.mockResolvedValue([cameraDefault]);
    mockedBulkMotion.mockRejectedValue(new ApiError(502, "Sync Module offline."));
    const wrapper = mountView();
    await flushPromises();

    await wrapper.find(`[data-testid="motion-enable-all-${HUB_ID}"]`).trigger("click");
    await flushPromises();

    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "error", detail: "Sync Module offline." }),
    );
  });

  it("toasts a generic error for a non-API bulk failure", async () => {
    mockedSyncModules.mockResolvedValue([hubFixture()]);
    mockedCameras.mockResolvedValue([cameraDefault]);
    mockedBulkMotion.mockRejectedValue(new TypeError("down"));
    const wrapper = mountView();
    await flushPromises();

    await wrapper.find(`[data-testid="motion-enable-all-${HUB_ID}"]`).trigger("click");
    await flushPromises();

    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "error", detail: "Unexpected error." }),
    );
  });

  it("hides the bulk motion buttons for a non-admin", async () => {
    mockedSyncModules.mockResolvedValue([hubFixture()]);
    mockedCameras.mockResolvedValue([cameraDefault]);
    const wrapper = mountView(false);
    await flushPromises();
    expect(wrapper.find(`[data-testid="motion-enable-all-${HUB_ID}"]`).exists()).toBe(false);
    expect(wrapper.find(`[data-testid="motion-disable-all-${HUB_ID}"]`).exists()).toBe(false);
  });
});

describe("SyncModuleView local storage section", () => {
  it("shows the local storage browser for a compatible physical hub", async () => {
    mockedSyncModules.mockResolvedValue([hubFixture()]);
    mockedCameras.mockResolvedValue([]);
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.findComponent({ name: "SyncModuleLocalStorageBrowser" }).exists()).toBe(true);
  });

  it("explains that a sync-less network has no USB storage to browse", async () => {
    mockedSyncModules.mockResolvedValue([
      hubFixture({ id: OWL_ID, is_physical_hub: false, local_storage_compatible: false }),
    ]);
    mockedCameras.mockResolvedValue([]);
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.find(`[data-testid="local-storage-unsupported-${OWL_ID}"]`).text()).toContain(
      "no physical Sync Module",
    );
  });

  it("explains that an incompatible physical hub doesn't support local storage", async () => {
    mockedSyncModules.mockResolvedValue([hubFixture({ local_storage_compatible: false })]);
    mockedCameras.mockResolvedValue([]);
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.find(`[data-testid="local-storage-unsupported-${HUB_ID}"]`).text()).toContain(
      "doesn't support local USB storage",
    );
  });
});
