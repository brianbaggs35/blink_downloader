import { flushPromises, mount } from "@vue/test-utils";
import ToggleSwitch from "primevue/toggleswitch";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/client";
import SettingsCamerasPanel from "@/components/SettingsCamerasPanel.vue";
import { makePinia, mountGlobal } from "./helpers";

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  listCameras: vi.fn(),
  updateCamera: vi.fn(),
}));

const toastAdd = vi.fn();
vi.mock("primevue/usetoast", () => ({
  useToast: () => ({ add: toastAdd }),
}));

import { listCameras, updateCamera } from "@/api";

const mockedList = vi.mocked(listCameras);
const mockedUpdate = vi.mocked(updateCamera);

const cameraA = {
  id: "aaaaaaaa-1111-2222-3333-444455556666",
  name: "Driveway",
  camera_type: "catalina",
  enabled: true,
  battery: "ok",
  last_synced_at: "2026-07-20T12:00:00Z",
  security_context: "Watches the driveway.",
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
});

function mountPanel() {
  return mount(SettingsCamerasPanel, { global: mountGlobal(makePinia()) });
}

describe("SettingsCamerasPanel loading", () => {
  it("shows a loading skeleton while fetching", () => {
    mockedList.mockReturnValue(new Promise(() => {}));
    const wrapper = mountPanel();
    expect(wrapper.find('[data-testid="cameras-loading"]').exists()).toBe(true);
  });

  it("shows the API error message when loading fails", async () => {
    mockedList.mockRejectedValue(new ApiError(500, "Server exploded"));
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find('[data-testid="cameras-load-error"]').text()).toBe("Server exploded");
  });

  it("falls back to a generic load error for non-API failures", async () => {
    mockedList.mockRejectedValue(new TypeError("down"));
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find('[data-testid="cameras-load-error"]').text()).toBe(
      "Could not load cameras.",
    );
  });

  it("shows an empty state when there are no cameras", async () => {
    mockedList.mockResolvedValue([]);
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find('[data-testid="cameras-empty"]').exists()).toBe(true);
  });

  it("renders each camera with its type, battery, and saved context", async () => {
    mockedList.mockResolvedValue([cameraA, cameraB]);
    const wrapper = mountPanel();
    await flushPromises();

    const rowA = wrapper.find(`[data-testid="camera-row-${cameraA.id}"]`);
    expect(rowA.text()).toContain("Driveway");
    expect(rowA.text()).toContain("catalina");
    expect(rowA.text()).toContain("Battery: ok");
    expect(rowA.text()).toContain("Syncing");
    const contextA = wrapper.find(`[data-testid="camera-context-${cameraA.id}"]`)
      .element as HTMLTextAreaElement;
    expect(contextA.value).toBe("Watches the driveway.");

    const rowB = wrapper.find(`[data-testid="camera-row-${cameraB.id}"]`);
    expect(rowB.text()).toContain("Paused");
    expect(rowB.text()).not.toContain("Battery:");
  });
});

describe("SettingsCamerasPanel toggling enabled", () => {
  beforeEach(() => {
    mockedList.mockResolvedValue([cameraA, cameraB]);
  });

  it("toggles a camera off and updates the row from the response", async () => {
    mockedUpdate.mockResolvedValue({ ...cameraA, enabled: false });
    const wrapper = mountPanel();
    await flushPromises();

    const toggles = wrapper.findAllComponents(ToggleSwitch);
    await toggles[0]!.vm.$emit("update:modelValue", false);
    await flushPromises();

    expect(mockedUpdate).toHaveBeenCalledWith(cameraA.id, false, cameraA.security_context);
    expect(wrapper.find(`[data-testid="camera-row-${cameraA.id}"]`).text()).toContain("Paused");
  });

  it("shows a toast when toggling fails", async () => {
    mockedUpdate.mockRejectedValue(new ApiError(400, "Camera not found."));
    const wrapper = mountPanel();
    await flushPromises();

    const toggles = wrapper.findAllComponents(ToggleSwitch);
    await toggles[0]!.vm.$emit("update:modelValue", false);
    await flushPromises();

    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "error", detail: "Camera not found." }),
    );
  });

  it("shows a generic toast for a non-API toggle failure", async () => {
    mockedUpdate.mockRejectedValue(new TypeError("down"));
    const wrapper = mountPanel();
    await flushPromises();

    const toggles = wrapper.findAllComponents(ToggleSwitch);
    await toggles[0]!.vm.$emit("update:modelValue", false);
    await flushPromises();

    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "error", detail: "Unexpected error." }),
    );
  });
});

describe("SettingsCamerasPanel editing context", () => {
  beforeEach(() => {
    mockedList.mockResolvedValue([cameraA, cameraB]);
  });

  it("hides the save link until the draft differs from the saved value", async () => {
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find(`[data-testid="camera-context-save-${cameraA.id}"]`).exists()).toBe(false);

    await wrapper
      .find(`[data-testid="camera-context-${cameraA.id}"]`)
      .setValue("Watches the driveway and the street.");
    expect(wrapper.find(`[data-testid="camera-context-save-${cameraA.id}"]`).exists()).toBe(true);
  });

  it("saves the new context and updates the row", async () => {
    const updated = { ...cameraA, security_context: "Updated context." };
    mockedUpdate.mockResolvedValue(updated);
    const wrapper = mountPanel();
    await flushPromises();

    await wrapper
      .find(`[data-testid="camera-context-${cameraA.id}"]`)
      .setValue("Updated context.");
    await wrapper.find(`[data-testid="camera-context-save-${cameraA.id}"]`).trigger("click");
    await flushPromises();

    expect(mockedUpdate).toHaveBeenCalledWith(cameraA.id, cameraA.enabled, "Updated context.");
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ summary: "Camera context saved" }),
    );
    expect(wrapper.find(`[data-testid="camera-context-save-${cameraA.id}"]`).exists()).toBe(false);
  });

  it("sends null when the context is cleared to blank", async () => {
    mockedUpdate.mockResolvedValue({ ...cameraA, security_context: null });
    const wrapper = mountPanel();
    await flushPromises();

    await wrapper.find(`[data-testid="camera-context-${cameraA.id}"]`).setValue("");
    await wrapper.find(`[data-testid="camera-context-save-${cameraA.id}"]`).trigger("click");
    await flushPromises();

    expect(mockedUpdate).toHaveBeenCalledWith(cameraA.id, cameraA.enabled, null);
  });

  it("shows a toast when saving context fails", async () => {
    mockedUpdate.mockRejectedValue(new ApiError(400, "Context too long."));
    const wrapper = mountPanel();
    await flushPromises();

    await wrapper
      .find(`[data-testid="camera-context-${cameraA.id}"]`)
      .setValue("Something new.");
    await wrapper.find(`[data-testid="camera-context-save-${cameraA.id}"]`).trigger("click");
    await flushPromises();

    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "error", detail: "Context too long." }),
    );
  });

  it("shows a generic toast for a non-API context save failure", async () => {
    mockedUpdate.mockRejectedValue(new TypeError("down"));
    const wrapper = mountPanel();
    await flushPromises();

    await wrapper
      .find(`[data-testid="camera-context-${cameraA.id}"]`)
      .setValue("Something new.");
    await wrapper.find(`[data-testid="camera-context-save-${cameraA.id}"]`).trigger("click");
    await flushPromises();

    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "error", detail: "Unexpected error." }),
    );
  });

  it("adds a context to a camera that had none", async () => {
    mockedUpdate.mockResolvedValue({ ...cameraB, security_context: "New context." });
    const wrapper = mountPanel();
    await flushPromises();

    await wrapper
      .find(`[data-testid="camera-context-${cameraB.id}"]`)
      .setValue("New context.");
    await wrapper.find(`[data-testid="camera-context-save-${cameraB.id}"]`).trigger("click");
    await flushPromises();

    expect(mockedUpdate).toHaveBeenCalledWith(cameraB.id, cameraB.enabled, "New context.");
  });
});
