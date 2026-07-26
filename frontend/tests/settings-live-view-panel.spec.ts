import { flushPromises, mount } from "@vue/test-utils";
import InputNumber from "primevue/inputnumber";
import Select from "primevue/select";
import ToggleSwitch from "primevue/toggleswitch";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/client";
import SettingsLiveViewPanel from "@/components/SettingsLiveViewPanel.vue";
import { makePinia, mountGlobal } from "./helpers";

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  listCameras: vi.fn(),
  getLiveViewSettings: vi.fn(),
  updateLiveViewSettings: vi.fn(),
}));

const toastAdd = vi.fn();
vi.mock("primevue/usetoast", () => ({ useToast: () => ({ add: toastAdd }) }));

import { getLiveViewSettings, listCameras, updateLiveViewSettings } from "@/api";

const mockedList = vi.mocked(listCameras);
const mockedGet = vi.mocked(getLiveViewSettings);
const mockedUpdate = vi.mocked(updateLiveViewSettings);

const camera = {
  id: "aaaaaaaa-1111-2222-3333-444455556666",
  name: "Driveway",
  camera_type: "catalina",
  enabled: true,
  battery: "ok",
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
  mockedList.mockResolvedValue([camera]);
  mockedGet.mockResolvedValue(defaultSettings);
});

function mountPanel() {
  return mount(SettingsLiveViewPanel, { global: mountGlobal(makePinia()) });
}

describe("SettingsLiveViewPanel", () => {
  it("shows a loading skeleton while fetching", () => {
    mockedGet.mockReturnValue(new Promise(() => {}));
    const wrapper = mountPanel();
    expect(wrapper.find('[data-testid="live-view-settings-loading"]').exists()).toBe(true);
  });

  it("shows the API error message when loading fails", async () => {
    mockedGet.mockRejectedValue(new ApiError(500, "Server exploded"));
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find('[data-testid="live-view-settings-load-error"]').text()).toBe(
      "Server exploded",
    );
  });

  it("falls back to a generic load error for non-API failures", async () => {
    mockedGet.mockRejectedValue(new TypeError("down"));
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find('[data-testid="live-view-settings-load-error"]').text()).toBe(
      "Could not load Live View settings.",
    );
  });

  it("populates the form from the loaded settings", async () => {
    mockedGet.mockResolvedValue({
      default_camera_id: camera.id,
      auto_refresh_enabled: true,
      auto_refresh_interval_seconds: 15,
    });
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find('[data-testid="default-camera"]').text()).toContain("Driveway");
  });

  it("edits every field and saves the new values", async () => {
    mockedUpdate.mockResolvedValue(defaultSettings);
    const wrapper = mountPanel();
    await flushPromises();

    await wrapper.findComponent(Select).vm.$emit("update:modelValue", camera.id);
    await wrapper.findComponent(ToggleSwitch).vm.$emit("update:modelValue", true);
    await wrapper.findComponent(InputNumber).vm.$emit("update:modelValue", 45);
    await wrapper.find('[data-testid="live-view-settings-form"]').trigger("submit.prevent");
    await flushPromises();

    expect(mockedUpdate).toHaveBeenCalledWith({
      default_camera_id: camera.id,
      auto_refresh_enabled: true,
      auto_refresh_interval_seconds: 45,
    });
  });

  it("saves the form and shows a success toast", async () => {
    mockedUpdate.mockResolvedValue(defaultSettings);
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="live-view-settings-form"]').trigger("submit.prevent");
    await flushPromises();
    expect(mockedUpdate).toHaveBeenCalledWith({
      default_camera_id: null,
      auto_refresh_enabled: false,
      auto_refresh_interval_seconds: 10,
    });
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "success", summary: "Live View settings saved" }),
    );
  });

  it("shows the API error message when saving fails", async () => {
    mockedUpdate.mockRejectedValue(new ApiError(400, "Bad camera id."));
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="live-view-settings-form"]').trigger("submit.prevent");
    await flushPromises();
    expect(wrapper.find('[data-testid="live-view-settings-save-error"]').text()).toBe(
      "Bad camera id.",
    );
  });

  it("falls back to a generic save error for non-API failures", async () => {
    mockedUpdate.mockRejectedValue(new TypeError("down"));
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="live-view-settings-form"]').trigger("submit.prevent");
    await flushPromises();
    expect(wrapper.find('[data-testid="live-view-settings-save-error"]').text()).toBe(
      "Unexpected error.",
    );
  });
});
