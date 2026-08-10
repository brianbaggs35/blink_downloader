import { flushPromises, mount } from "@vue/test-utils";
import ToggleSwitch from "primevue/toggleswitch";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/client";
import SettingsCamerasPanel from "@/components/SettingsCamerasPanel.vue";
import { makePinia, mountGlobal } from "./helpers";

import type { CameraRead } from "@/api";

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
    // camera_type "catalina" is translated to its real hardware name -
    // see frontend/src/lib/cameraModels.ts.
    expect(rowA.text()).toContain("Blink Outdoor Gen 3");
    expect(wrapper.find(`[data-testid="camera-battery-${cameraA.id}"]`).text()).toBe("OK");
    expect(rowA.text()).toContain("Syncing");
    const contextA = wrapper.find(`[data-testid="camera-context-${cameraA.id}"]`)
      .element as HTMLTextAreaElement;
    expect(contextA.value).toBe("Watches the driveway.");

    const rowB = wrapper.find(`[data-testid="camera-row-${cameraB.id}"]`);
    expect(rowB.text()).toContain("Paused");
    expect(wrapper.find(`[data-testid="camera-battery-${cameraB.id}"]`).exists()).toBe(false);
    // An unmapped codename ("sedona") falls back to the raw string.
    expect(rowB.text()).toContain("sedona");
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

describe("SettingsCamerasPanel saving all", () => {
  beforeEach(() => {
    mockedList.mockResolvedValue([cameraA, cameraB]);
  });

  it("disables Save all until at least one camera is dirty", async () => {
    const wrapper = mountPanel();
    await flushPromises();

    expect(
      wrapper.find('[data-testid="camera-save-all"]').attributes("disabled"),
    ).toBeDefined();

    await wrapper
      .find(`[data-testid="camera-context-${cameraA.id}"]`)
      .setValue("Watches the driveway and the street.");

    expect(
      wrapper.find('[data-testid="camera-save-all"]').attributes("disabled"),
    ).toBeUndefined();
  });

  it("saves every dirty camera and leaves untouched ones alone", async () => {
    mockedUpdate.mockImplementation(async (id, enabled, securityContext) =>
      id === cameraA.id
        ? { ...cameraA, security_context: securityContext ?? null }
        : { ...cameraB, security_context: securityContext ?? null, enabled },
    );
    const wrapper = mountPanel();
    await flushPromises();

    await wrapper
      .find(`[data-testid="camera-context-${cameraA.id}"]`)
      .setValue("Updated driveway context.");
    await wrapper
      .find(`[data-testid="camera-context-${cameraB.id}"]`)
      .setValue("New backyard context.");
    await wrapper.find('[data-testid="camera-save-all"]').trigger("click");
    await flushPromises();

    expect(mockedUpdate).toHaveBeenCalledTimes(2);
    expect(mockedUpdate).toHaveBeenCalledWith(
      cameraA.id,
      cameraA.enabled,
      "Updated driveway context.",
    );
    expect(mockedUpdate).toHaveBeenCalledWith(
      cameraB.id,
      cameraB.enabled,
      "New backyard context.",
    );
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "success", summary: "Saved 2 camera contexts" }),
    );
    // Both rows are clean again - their individual Save buttons disappear.
    expect(wrapper.find(`[data-testid="camera-context-save-${cameraA.id}"]`).exists()).toBe(
      false,
    );
    expect(wrapper.find(`[data-testid="camera-context-save-${cameraB.id}"]`).exists()).toBe(
      false,
    );
  });

  it("sends null for a camera whose context was cleared to blank in a bulk save", async () => {
    mockedUpdate.mockImplementation(async (id, enabled, securityContext) =>
      id === cameraA.id
        ? { ...cameraA, security_context: securityContext ?? null }
        : { ...cameraB, security_context: securityContext ?? null, enabled },
    );
    const wrapper = mountPanel();
    await flushPromises();

    await wrapper.find(`[data-testid="camera-context-${cameraA.id}"]`).setValue("");
    await wrapper.find('[data-testid="camera-save-all"]').trigger("click");
    await flushPromises();

    expect(mockedUpdate).toHaveBeenCalledWith(cameraA.id, cameraA.enabled, null);
  });

  it("uses singular phrasing for a single-camera save", async () => {
    mockedUpdate.mockResolvedValue({ ...cameraA, security_context: "Solo edit." });
    const wrapper = mountPanel();
    await flushPromises();

    await wrapper.find(`[data-testid="camera-context-${cameraA.id}"]`).setValue("Solo edit.");
    await wrapper.find('[data-testid="camera-save-all"]').trigger("click");
    await flushPromises();

    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ summary: "Saved 1 camera context" }),
    );
  });

  it("reports a partial failure without losing the successful save", async () => {
    mockedUpdate.mockImplementation(async (id, _enabled, securityContext) => {
      if (id === cameraA.id) {
        throw new ApiError(400, "Context too long.");
      }
      return { ...cameraB, security_context: securityContext ?? null };
    });
    const wrapper = mountPanel();
    await flushPromises();

    await wrapper
      .find(`[data-testid="camera-context-${cameraA.id}"]`)
      .setValue("Way too long.");
    await wrapper
      .find(`[data-testid="camera-context-${cameraB.id}"]`)
      .setValue("Fine context.");
    await wrapper.find('[data-testid="camera-save-all"]').trigger("click");
    await flushPromises();

    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({
        severity: "warn",
        summary: "Saved 1 camera context",
        detail: "1 could not be saved.",
      }),
    );
    // The failed row is still dirty (still shows its own Save button); the
    // successful one is clean.
    expect(wrapper.find(`[data-testid="camera-context-save-${cameraA.id}"]`).exists()).toBe(true);
    expect(wrapper.find(`[data-testid="camera-context-save-${cameraB.id}"]`).exists()).toBe(
      false,
    );
  });

  it("disables Save all while a bulk save is in flight", async () => {
    let resolveUpdate!: (value: CameraRead) => void;
    mockedUpdate.mockReturnValue(
      new Promise((resolve) => {
        resolveUpdate = resolve;
      }),
    );
    const wrapper = mountPanel();
    await flushPromises();

    await wrapper
      .find(`[data-testid="camera-context-${cameraA.id}"]`)
      .setValue("In flight.");
    await wrapper.find('[data-testid="camera-save-all"]').trigger("click");
    await flushPromises();

    expect(
      wrapper.find('[data-testid="camera-save-all"]').attributes("disabled"),
    ).toBeDefined();

    resolveUpdate({ ...cameraA, security_context: "In flight." });
    await flushPromises();

    expect(
      wrapper.find('[data-testid="camera-save-all"]').attributes("disabled"),
    ).toBeDefined();
  });
});
