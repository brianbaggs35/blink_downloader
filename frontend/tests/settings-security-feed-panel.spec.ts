import { flushPromises, mount } from "@vue/test-utils";
import Checkbox from "primevue/checkbox";
import InputNumber from "primevue/inputnumber";
import Select from "primevue/select";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/client";
import SettingsSecurityFeedPanel from "@/components/SettingsSecurityFeedPanel.vue";
import { makePinia, mountGlobal } from "./helpers";

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  listCameras: vi.fn(),
  getSecurityFeedSettings: vi.fn(),
  updateSecurityFeedSettings: vi.fn(),
}));

const toastAdd = vi.fn();
vi.mock("primevue/usetoast", () => ({ useToast: () => ({ add: toastAdd }) }));

import { getSecurityFeedSettings, listCameras, updateSecurityFeedSettings } from "@/api";

const mockedList = vi.mocked(listCameras);
const mockedGet = vi.mocked(getSecurityFeedSettings);
const mockedUpdate = vi.mocked(updateSecurityFeedSettings);

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

const defaultSettings = { camera_ids: [], columns: 2, refresh_interval_seconds: 20 };

beforeEach(() => {
  vi.clearAllMocks();
  mockedList.mockResolvedValue([cameraA, cameraB]);
  mockedGet.mockResolvedValue(defaultSettings);
});

function mountPanel() {
  return mount(SettingsSecurityFeedPanel, { global: mountGlobal(makePinia()) });
}

describe("SettingsSecurityFeedPanel loading", () => {
  it("shows a loading skeleton while fetching", () => {
    mockedGet.mockReturnValue(new Promise(() => {}));
    const wrapper = mountPanel();
    expect(wrapper.find('[data-testid="security-feed-settings-loading"]').exists()).toBe(true);
  });

  it("shows the API error message when loading fails", async () => {
    mockedGet.mockRejectedValue(new ApiError(500, "Server exploded"));
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find('[data-testid="security-feed-settings-load-error"]').text()).toBe(
      "Server exploded",
    );
  });

  it("falls back to a generic load error for non-API failures", async () => {
    mockedGet.mockRejectedValue(new TypeError("down"));
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find('[data-testid="security-feed-settings-load-error"]').text()).toBe(
      "Could not load Security Feed settings.",
    );
  });

  it("shows an empty message when there are no cameras", async () => {
    mockedList.mockResolvedValue([]);
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find('[data-testid="security-feed-settings-empty"]').exists()).toBe(true);
  });
});

describe("SettingsSecurityFeedPanel camera selection", () => {
  it("lists every camera under 'not shown' when nothing is selected yet", async () => {
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.text()).toContain("Nothing chosen yet");
    expect(wrapper.find(`[data-testid="security-feed-camera-${cameraA.id}"]`).exists()).toBe(true);
  });

  it("moves a camera into the shown list when checked", async () => {
    const wrapper = mountPanel();
    await flushPromises();
    const checkboxes = wrapper.findAllComponents(Checkbox);
    await checkboxes[0]!.vm.$emit("update:modelValue", true);
    await flushPromises();
    expect(wrapper.find(`[data-testid="move-up-${cameraA.id}"]`).exists()).toBe(true);
  });

  it("reorders shown cameras with the up/down buttons", async () => {
    mockedGet.mockResolvedValue({ ...defaultSettings, camera_ids: [cameraA.id, cameraB.id] });
    const wrapper = mountPanel();
    await flushPromises();

    await wrapper.find(`[data-testid="move-down-${cameraA.id}"]`).trigger("click");
    await flushPromises();
    // cameraA is now second, so its "move down" button should be disabled.
    const movedDown = wrapper.find(`[data-testid="move-down-${cameraA.id}"]`)
      .element as HTMLButtonElement;
    expect(movedDown.disabled).toBe(true);

    await wrapper.find(`[data-testid="move-up-${cameraA.id}"]`).trigger("click");
    await flushPromises();
    const movedUp = wrapper.find(`[data-testid="move-up-${cameraA.id}"]`)
      .element as HTMLButtonElement;
    expect(movedUp.disabled).toBe(true);
  });

  it("unchecking a shown camera moves it back to 'not shown'", async () => {
    mockedGet.mockResolvedValue({ ...defaultSettings, camera_ids: [cameraA.id] });
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find(`[data-testid="move-up-${cameraA.id}"]`).exists()).toBe(true);

    const checkbox = wrapper.findComponent(Checkbox);
    await checkbox.vm.$emit("update:modelValue", false);
    await flushPromises();
    expect(wrapper.find(`[data-testid="move-up-${cameraA.id}"]`).exists()).toBe(false);
    expect(wrapper.text()).toContain("Nothing chosen yet");
  });
});

describe("SettingsSecurityFeedPanel save", () => {
  it("edits the columns and interval fields and saves them", async () => {
    mockedUpdate.mockResolvedValue(defaultSettings);
    const wrapper = mountPanel();
    await flushPromises();

    await wrapper.findComponent(Select).vm.$emit("update:modelValue", 4);
    await wrapper.findComponent(InputNumber).vm.$emit("update:modelValue", 60);
    await wrapper.find('[data-testid="security-feed-settings-form"]').trigger("submit.prevent");
    await flushPromises();

    expect(mockedUpdate).toHaveBeenCalledWith({
      camera_ids: [],
      columns: 4,
      refresh_interval_seconds: 60,
    });
  });

  it("saves the selection, columns, and interval", async () => {
    mockedGet.mockResolvedValue({ ...defaultSettings, camera_ids: [cameraA.id] });
    mockedUpdate.mockResolvedValue({ ...defaultSettings, camera_ids: [cameraA.id] });
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="security-feed-settings-form"]').trigger("submit.prevent");
    await flushPromises();
    expect(mockedUpdate).toHaveBeenCalledWith({
      camera_ids: [cameraA.id],
      columns: 2,
      refresh_interval_seconds: 20,
    });
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "success", summary: "Security Feed settings saved" }),
    );
  });

  it("shows the API error message when saving fails", async () => {
    mockedUpdate.mockRejectedValue(new ApiError(400, "Too many cameras."));
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="security-feed-settings-form"]').trigger("submit.prevent");
    await flushPromises();
    expect(wrapper.find('[data-testid="security-feed-settings-save-error"]').text()).toBe(
      "Too many cameras.",
    );
  });

  it("falls back to a generic save error for non-API failures", async () => {
    mockedUpdate.mockRejectedValue(new TypeError("down"));
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="security-feed-settings-form"]').trigger("submit.prevent");
    await flushPromises();
    expect(wrapper.find('[data-testid="security-feed-settings-save-error"]').text()).toBe(
      "Unexpected error.",
    );
  });
});
