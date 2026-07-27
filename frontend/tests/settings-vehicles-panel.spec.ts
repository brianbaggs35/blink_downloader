import { flushPromises, mount } from "@vue/test-utils";
import ToggleSwitch from "primevue/toggleswitch";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  listCameras: vi.fn(),
  getVehicle: vi.fn(),
  putVehicle: vi.fn(),
  deleteVehicle: vi.fn(),
  captureVehicleReferenceFrame: vi.fn(),
}));

const toastAdd = vi.fn();
vi.mock("primevue/usetoast", () => ({ useToast: () => ({ add: toastAdd }) }));

const confirmRequire = vi.fn();
vi.mock("primevue/useconfirm", () => ({ useConfirm: () => ({ require: confirmRequire }) }));

import {
  captureVehicleReferenceFrame,
  deleteVehicle,
  getVehicle,
  listCameras,
  putVehicle,
} from "@/api";
import { ApiError } from "@/api/client";
import SettingsVehiclesPanel from "@/components/SettingsVehiclesPanel.vue";
import { makePinia, mountGlobal } from "./helpers";

const mockedCameras = vi.mocked(listCameras);
const mockedGetVehicle = vi.mocked(getVehicle);
const mockedPutVehicle = vi.mocked(putVehicle);
const mockedDeleteVehicle = vi.mocked(deleteVehicle);
const mockedCapture = vi.mocked(captureVehicleReferenceFrame);

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
  name: "Garage",
  camera_type: "sedona",
  enabled: true,
  battery: null,
  last_synced_at: null,
  security_context: null,
};

const savedVehicle = {
  id: "vvvvvvvv-1111-2222-3333-444455556666",
  camera_id: cameraA.id,
  camera_name: cameraA.name,
  description: "Blue Honda Civic",
  outline_points: [
    [0.2, 0.3],
    [0.6, 0.3],
    [0.6, 0.7],
  ],
  has_reference_frame: true,
  estimated_length_feet: 15,
  distance_threshold_feet: 6,
  enabled: true,
  updated_at: "2026-07-20T12:00:00Z",
};

function notFound(): ApiError {
  return new ApiError(404, "No vehicle registered for this camera.");
}

function rectOf(width: number, height: number) {
  return {
    left: 0,
    top: 0,
    right: width,
    bottom: height,
    width,
    height,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  Element.prototype.getBoundingClientRect = vi.fn(() => rectOf(400, 300));
});

function mountPanel() {
  return mount(SettingsVehiclesPanel, { global: mountGlobal(makePinia()) });
}

describe("SettingsVehiclesPanel loading cameras", () => {
  it("shows a loading skeleton while fetching cameras", () => {
    mockedCameras.mockReturnValue(new Promise(() => {}));
    const wrapper = mountPanel();
    expect(wrapper.find('[data-testid="vehicles-cameras-loading"]').exists()).toBe(true);
  });

  it("shows the API error message when loading cameras fails", async () => {
    mockedCameras.mockRejectedValue(new ApiError(500, "Server exploded"));
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find('[data-testid="vehicles-cameras-error"]').text()).toBe(
      "Server exploded",
    );
  });

  it("falls back to a generic cameras error for non-API failures", async () => {
    mockedCameras.mockRejectedValue(new TypeError("down"));
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find('[data-testid="vehicles-cameras-error"]').text()).toBe(
      "Could not load cameras.",
    );
  });

  it("shows an info message when there are no cameras", async () => {
    mockedCameras.mockResolvedValue([]);
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find('[data-testid="vehicles-no-cameras"]').exists()).toBe(true);
  });
});

describe("SettingsVehiclesPanel per-camera loading", () => {
  it("treats a 404 as unconfigured, offering to capture a reference frame", async () => {
    mockedCameras.mockResolvedValue([cameraA]);
    mockedGetVehicle.mockRejectedValue(notFound());
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find(`[data-testid="capture-frame-${cameraA.id}"]`).exists()).toBe(true);
    expect(wrapper.find(`[data-testid="vehicle-error-${cameraA.id}"]`).exists()).toBe(false);
  });

  it("shows a per-camera loading skeleton while its vehicle is still being fetched", async () => {
    mockedCameras.mockResolvedValue([cameraA]);
    mockedGetVehicle.mockReturnValue(new Promise(() => {}));
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find(`[data-testid="vehicle-loading-${cameraA.id}"]`).exists()).toBe(true);
  });

  it("shows the API error message for a non-404 load failure", async () => {
    mockedCameras.mockResolvedValue([cameraA]);
    mockedGetVehicle.mockRejectedValue(new ApiError(500, "Server exploded"));
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find(`[data-testid="vehicle-error-${cameraA.id}"]`).text()).toBe(
      "Server exploded",
    );
  });

  it("falls back to a generic per-camera error for non-API failures", async () => {
    mockedCameras.mockResolvedValue([cameraA]);
    mockedGetVehicle.mockRejectedValue(new TypeError("down"));
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find(`[data-testid="vehicle-error-${cameraA.id}"]`).text()).toBe(
      "Could not load this camera's vehicle setup.",
    );
  });

  it("populates the form from an existing vehicle, including the outline and enabled toggle", async () => {
    mockedCameras.mockResolvedValue([cameraA]);
    mockedGetVehicle.mockResolvedValue(savedVehicle);
    const wrapper = mountPanel();
    await flushPromises();

    const description = wrapper.find(`[data-testid="vehicle-description-${cameraA.id}"]`)
      .element as HTMLInputElement;
    expect(description.value).toBe("Blue Honda Civic");
    expect(wrapper.find(`[data-testid="outline-point-${cameraA.id}-2"]`).exists()).toBe(true);
    expect(wrapper.find(`[data-testid="vehicle-enabled-${cameraA.id}"]`).exists()).toBe(true);
    expect(wrapper.find(`[data-testid="delete-vehicle-${cameraA.id}"]`).exists()).toBe(true);
  });

  it("loads multiple cameras independently", async () => {
    mockedCameras.mockResolvedValue([cameraA, cameraB]);
    mockedGetVehicle.mockImplementation((id) =>
      id === cameraA.id ? Promise.resolve(savedVehicle) : Promise.reject(notFound()),
    );
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find(`[data-testid="outline-svg-${cameraA.id}"]`).exists()).toBe(true);
    expect(wrapper.find(`[data-testid="capture-frame-${cameraB.id}"]`).exists()).toBe(true);
  });
});

describe("SettingsVehiclesPanel capturing a reference frame", () => {
  beforeEach(() => {
    mockedCameras.mockResolvedValue([cameraA]);
    mockedGetVehicle.mockRejectedValue(notFound());
  });

  it("captures a frame and reveals the outline editor", async () => {
    mockedCapture.mockResolvedValue(undefined);
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find(`[data-testid="capture-frame-${cameraA.id}"]`).trigger("click");
    await flushPromises();
    expect(mockedCapture).toHaveBeenCalledWith(cameraA.id);
    expect(wrapper.find(`[data-testid="outline-svg-${cameraA.id}"]`).exists()).toBe(true);
  });

  it("shows the API error message when capture fails", async () => {
    mockedCapture.mockRejectedValue(new ApiError(409, "No downloaded clips yet."));
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find(`[data-testid="capture-frame-${cameraA.id}"]`).trigger("click");
    await flushPromises();
    expect(wrapper.find(`[data-testid="vehicle-error-${cameraA.id}"]`).text()).toBe(
      "No downloaded clips yet.",
    );
  });

  it("falls back to a generic capture error for non-API failures", async () => {
    mockedCapture.mockRejectedValue(new TypeError("down"));
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find(`[data-testid="capture-frame-${cameraA.id}"]`).trigger("click");
    await flushPromises();
    expect(wrapper.find(`[data-testid="vehicle-error-${cameraA.id}"]`).text()).toContain(
      "at least one downloaded clip",
    );
  });

  it("re-captures from within the editor and busts the image cache", async () => {
    mockedGetVehicle.mockResolvedValue(savedVehicle);
    mockedCapture.mockResolvedValue(undefined);
    const wrapper = mountPanel();
    await flushPromises();
    const srcBefore = (
      wrapper.find(`[data-testid="outline-svg-${cameraA.id}"]`)
        .element.previousElementSibling as HTMLImageElement
    ).src;
    await wrapper.find(`[data-testid="recapture-frame-${cameraA.id}"]`).trigger("click");
    await flushPromises();
    expect(mockedCapture).toHaveBeenCalledWith(cameraA.id);
    const srcAfter = (
      wrapper.find(`[data-testid="outline-svg-${cameraA.id}"]`)
        .element.previousElementSibling as HTMLImageElement
    ).src;
    expect(srcAfter).not.toBe(srcBefore);
  });
});

describe("SettingsVehiclesPanel drawing the outline", () => {
  beforeEach(() => {
    mockedCameras.mockResolvedValue([cameraA]);
    mockedGetVehicle.mockRejectedValue(notFound());
  });

  async function mountWithFrame() {
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find(`[data-testid="capture-frame-${cameraA.id}"]`).trigger("click");
    await flushPromises();
    return wrapper;
  }

  it("adds a point where the image is clicked", async () => {
    mockedCapture.mockResolvedValue(undefined);
    const wrapper = await mountWithFrame();
    await wrapper
      .find(`[data-testid="outline-svg-${cameraA.id}"]`)
      .trigger("click", { clientX: 200, clientY: 150 });
    const point = wrapper.find(`[data-testid="outline-point-${cameraA.id}-0"]`);
    expect(point.attributes("cx")).toBe("50");
    expect(point.attributes("cy")).toBe("50");
  });

  it("ignores clicks when the svg has no rendered size yet", async () => {
    mockedCapture.mockResolvedValue(undefined);
    const wrapper = await mountWithFrame();
    Element.prototype.getBoundingClientRect = vi.fn(() => rectOf(0, 0));
    await wrapper
      .find(`[data-testid="outline-svg-${cameraA.id}"]`)
      .trigger("click", { clientX: 200, clientY: 150 });
    expect(wrapper.find(`[data-testid="outline-point-${cameraA.id}-0"]`).exists()).toBe(false);
  });

  it("removes a point on a press-and-release with no movement, without adding a new one underneath it", async () => {
    mockedCapture.mockResolvedValue(undefined);
    const wrapper = await mountWithFrame();
    const svg = wrapper.find(`[data-testid="outline-svg-${cameraA.id}"]`);
    await svg.trigger("click", { clientX: 40, clientY: 30 });
    await svg.trigger("click", { clientX: 360, clientY: 30 });
    await svg.trigger("click", { clientX: 360, clientY: 270 });
    expect(wrapper.findAll(`[data-testid^="outline-point-${cameraA.id}-"]`)).toHaveLength(3);

    await wrapper
      .find(`[data-testid="outline-point-${cameraA.id}-1"]`)
      .trigger("pointerdown", { clientX: 360, clientY: 30 });
    await svg.trigger("pointerup", { clientX: 360, clientY: 30 });
    const remaining = wrapper.findAll(`[data-testid^="outline-point-${cameraA.id}-"]`);
    expect(remaining).toHaveLength(2);
  });

  it("swallows a point's own click event instead of letting it bubble into adding a new point", async () => {
    // Real browsers fire a "click" after any same-target pointerdown+pointerup
    // - actual removal is handled by endPointDrag, so the point's own
    // @click.stop only needs to stop this from bubbling into the svg's
    // addPoint handler and creating an unwanted extra point underneath it.
    mockedCapture.mockResolvedValue(undefined);
    const wrapper = await mountWithFrame();
    const svg = wrapper.find(`[data-testid="outline-svg-${cameraA.id}"]`);
    await svg.trigger("click", { clientX: 40, clientY: 30 });
    expect(wrapper.findAll(`[data-testid^="outline-point-${cameraA.id}-"]`)).toHaveLength(1);

    await wrapper.find(`[data-testid="outline-point-${cameraA.id}-0"]`).trigger("click");
    expect(wrapper.findAll(`[data-testid^="outline-point-${cameraA.id}-"]`)).toHaveLength(1);
  });

  it("drags a point to reposition it instead of removing it", async () => {
    mockedCapture.mockResolvedValue(undefined);
    const wrapper = await mountWithFrame();
    const svg = wrapper.find(`[data-testid="outline-svg-${cameraA.id}"]`);
    await svg.trigger("click", { clientX: 40, clientY: 30 });
    await svg.trigger("click", { clientX: 360, clientY: 30 });
    await svg.trigger("click", { clientX: 360, clientY: 270 });

    await wrapper
      .find(`[data-testid="outline-point-${cameraA.id}-0"]`)
      .trigger("pointerdown", { clientX: 40, clientY: 30 });
    await svg.trigger("pointermove", { clientX: 200, clientY: 150 });
    await svg.trigger("pointerup", { clientX: 200, clientY: 150 });

    const points = wrapper.findAll(`[data-testid^="outline-point-${cameraA.id}-"]`);
    expect(points).toHaveLength(3);
    const moved = wrapper.find(`[data-testid="outline-point-${cameraA.id}-0"]`);
    expect(moved.attributes("cx")).toBe("50");
    expect(moved.attributes("cy")).toBe("50");
  });

  it("ignores drag movement for a different camera's outline", async () => {
    mockedCameras.mockResolvedValue([cameraA, cameraB]);
    mockedGetVehicle.mockRejectedValue(notFound());
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find(`[data-testid="capture-frame-${cameraA.id}"]`).trigger("click");
    await wrapper.find(`[data-testid="capture-frame-${cameraB.id}"]`).trigger("click");
    await flushPromises();

    const svgA = wrapper.find(`[data-testid="outline-svg-${cameraA.id}"]`);
    await svgA.trigger("click", { clientX: 40, clientY: 30 });
    await wrapper
      .find(`[data-testid="outline-point-${cameraA.id}-0"]`)
      .trigger("pointerdown", { clientX: 40, clientY: 30 });

    // A pointermove/pointerup bubbling through camera B's own svg must not
    // affect camera A's in-progress drag.
    const svgB = wrapper.find(`[data-testid="outline-svg-${cameraB.id}"]`);
    await svgB.trigger("pointermove", { clientX: 200, clientY: 150 });
    await svgB.trigger("pointerup", { clientX: 200, clientY: 150 });

    const point = wrapper.find(`[data-testid="outline-point-${cameraA.id}-0"]`);
    expect(point.attributes("cx")).toBe("10");
    expect(point.attributes("cy")).toBe("10");
  });

  it("counts as a drag when only the vertical movement crosses the threshold", async () => {
    mockedCapture.mockResolvedValue(undefined);
    const wrapper = await mountWithFrame();
    const svg = wrapper.find(`[data-testid="outline-svg-${cameraA.id}"]`);
    await svg.trigger("click", { clientX: 40, clientY: 30 });

    await wrapper
      .find(`[data-testid="outline-point-${cameraA.id}-0"]`)
      .trigger("pointerdown", { clientX: 40, clientY: 30 });
    // x barely moves (well under DRAG_MOVE_THRESHOLD); y moves well past it.
    await svg.trigger("pointermove", { clientX: 41, clientY: 150 });
    await svg.trigger("pointerup", { clientX: 41, clientY: 150 });

    expect(wrapper.findAll(`[data-testid^="outline-point-${cameraA.id}-"]`)).toHaveLength(1);
    const point = wrapper.find(`[data-testid="outline-point-${cameraA.id}-0"]`);
    expect(point.attributes("cy")).not.toBe("10");
  });

  it("treats a sub-threshold jiggle in both axes as a click, still removing the point", async () => {
    mockedCapture.mockResolvedValue(undefined);
    const wrapper = await mountWithFrame();
    const svg = wrapper.find(`[data-testid="outline-svg-${cameraA.id}"]`);
    await svg.trigger("click", { clientX: 40, clientY: 30 });

    await wrapper
      .find(`[data-testid="outline-point-${cameraA.id}-0"]`)
      .trigger("pointerdown", { clientX: 40, clientY: 30 });
    // Both axes move by 1px - well under DRAG_MOVE_THRESHOLD (2px/1.5px here).
    await svg.trigger("pointermove", { clientX: 41, clientY: 31 });
    await svg.trigger("pointerup", { clientX: 41, clientY: 31 });

    expect(wrapper.findAll(`[data-testid^="outline-point-${cameraA.id}-"]`)).toHaveLength(0);
  });

  it("ignores drag movement once the svg has no rendered size (e.g. mid-layout-change)", async () => {
    mockedCapture.mockResolvedValue(undefined);
    const wrapper = await mountWithFrame();
    const svg = wrapper.find(`[data-testid="outline-svg-${cameraA.id}"]`);
    await svg.trigger("click", { clientX: 40, clientY: 30 });

    await wrapper
      .find(`[data-testid="outline-point-${cameraA.id}-0"]`)
      .trigger("pointerdown", { clientX: 40, clientY: 30 });
    Element.prototype.getBoundingClientRect = vi.fn(() => rectOf(0, 0));
    await svg.trigger("pointermove", { clientX: 200, clientY: 150 });

    const point = wrapper.find(`[data-testid="outline-point-${cameraA.id}-0"]`);
    expect(point.attributes("cx")).toBe("10");
    expect(point.attributes("cy")).toBe("10");
  });

  it("ends the drag without removing the point when the pointer leaves the image", async () => {
    mockedCapture.mockResolvedValue(undefined);
    const wrapper = await mountWithFrame();
    const svg = wrapper.find(`[data-testid="outline-svg-${cameraA.id}"]`);
    await svg.trigger("click", { clientX: 40, clientY: 30 });

    await wrapper
      .find(`[data-testid="outline-point-${cameraA.id}-0"]`)
      .trigger("pointerdown", { clientX: 40, clientY: 30 });
    await svg.trigger("pointermove", { clientX: 5, clientY: 5 });
    await svg.trigger("pointerleave", { clientX: -20, clientY: -20 });

    expect(wrapper.findAll(`[data-testid^="outline-point-${cameraA.id}-"]`)).toHaveLength(1);
  });

  it("draws the polygon once at least two points exist", async () => {
    mockedCapture.mockResolvedValue(undefined);
    const wrapper = await mountWithFrame();
    const svg = wrapper.find(`[data-testid="outline-svg-${cameraA.id}"]`);
    expect(svg.find("polygon").exists()).toBe(false);
    await svg.trigger("click", { clientX: 40, clientY: 30 });
    await svg.trigger("click", { clientX: 360, clientY: 30 });
    expect(svg.find("polygon").exists()).toBe(true);
  });

  it("undoes the last point", async () => {
    mockedCapture.mockResolvedValue(undefined);
    const wrapper = await mountWithFrame();
    const svg = wrapper.find(`[data-testid="outline-svg-${cameraA.id}"]`);
    await svg.trigger("click", { clientX: 40, clientY: 30 });
    await svg.trigger("click", { clientX: 360, clientY: 30 });
    await wrapper.find(`[data-testid="undo-point-${cameraA.id}"]`).trigger("click");
    expect(wrapper.findAll(`[data-testid^="outline-point-${cameraA.id}-"]`)).toHaveLength(1);
  });

  it("disables Undo and Clear when there are no points yet", async () => {
    mockedCapture.mockResolvedValue(undefined);
    const wrapper = await mountWithFrame();
    expect(
      wrapper.find(`[data-testid="undo-point-${cameraA.id}"]`).attributes("disabled"),
    ).toBeDefined();
    expect(
      wrapper.find(`[data-testid="clear-points-${cameraA.id}"]`).attributes("disabled"),
    ).toBeDefined();
  });

  it("clears all points", async () => {
    mockedCapture.mockResolvedValue(undefined);
    const wrapper = await mountWithFrame();
    const svg = wrapper.find(`[data-testid="outline-svg-${cameraA.id}"]`);
    await svg.trigger("click", { clientX: 40, clientY: 30 });
    await svg.trigger("click", { clientX: 360, clientY: 30 });
    await wrapper.find(`[data-testid="clear-points-${cameraA.id}"]`).trigger("click");
    expect(wrapper.findAll(`[data-testid^="outline-point-${cameraA.id}-"]`)).toHaveLength(0);
  });
});

describe("SettingsVehiclesPanel saving", () => {
  async function mountWithThreePoints() {
    mockedCameras.mockResolvedValue([cameraA]);
    mockedGetVehicle.mockRejectedValue(notFound());
    mockedCapture.mockResolvedValue(undefined);
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find(`[data-testid="capture-frame-${cameraA.id}"]`).trigger("click");
    await flushPromises();
    const svg = wrapper.find(`[data-testid="outline-svg-${cameraA.id}"]`);
    await svg.trigger("click", { clientX: 40, clientY: 30 });
    await svg.trigger("click", { clientX: 360, clientY: 30 });
    await svg.trigger("click", { clientX: 360, clientY: 270 });
    return wrapper;
  }

  it("disables Save with fewer than three points or a blank description", async () => {
    const wrapper = await mountWithThreePoints();
    const saveButton = wrapper.find(`[data-testid="save-vehicle-${cameraA.id}"]`);
    expect(saveButton.attributes("disabled")).toBeDefined();
    await wrapper
      .find(`[data-testid="vehicle-description-${cameraA.id}"]`)
      .setValue("   ");
    expect(wrapper.find(`[data-testid="save-vehicle-${cameraA.id}"]`).attributes("disabled")).toBeDefined();
  });

  it("enables Save once there are enough points and a description, then saves", async () => {
    mockedPutVehicle.mockResolvedValue({ ...savedVehicle, description: "My car" });
    const wrapper = await mountWithThreePoints();
    await wrapper.find(`[data-testid="vehicle-description-${cameraA.id}"]`).setValue("My car");
    const saveButton = wrapper.find(`[data-testid="save-vehicle-${cameraA.id}"]`);
    expect(saveButton.attributes("disabled")).toBeUndefined();
    await saveButton.trigger("click");
    await flushPromises();

    expect(mockedPutVehicle).toHaveBeenCalledWith(cameraA.id, {
      description: "My car",
      outline_points: [
        [0.1, 0.1],
        [0.9, 0.1],
        [0.9, 0.9],
      ],
      estimated_length_feet: 15,
      distance_threshold_feet: 6,
      enabled: true,
    });
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ summary: "Saved vehicle protection for Driveway" }),
    );
    expect(wrapper.find(`[data-testid="delete-vehicle-${cameraA.id}"]`).exists()).toBe(true);
  });

  it("trims the description before saving", async () => {
    mockedPutVehicle.mockResolvedValue(savedVehicle);
    const wrapper = await mountWithThreePoints();
    await wrapper
      .find(`[data-testid="vehicle-description-${cameraA.id}"]`)
      .setValue("  My car  ");
    await wrapper.find(`[data-testid="save-vehicle-${cameraA.id}"]`).trigger("click");
    await flushPromises();
    expect(mockedPutVehicle).toHaveBeenCalledWith(
      cameraA.id,
      expect.objectContaining({ description: "My car" }),
    );
  });

  it("shows the API error message when saving fails", async () => {
    mockedPutVehicle.mockRejectedValue(new ApiError(400, "Description too long."));
    const wrapper = await mountWithThreePoints();
    await wrapper.find(`[data-testid="vehicle-description-${cameraA.id}"]`).setValue("My car");
    await wrapper.find(`[data-testid="save-vehicle-${cameraA.id}"]`).trigger("click");
    await flushPromises();
    expect(wrapper.find(`[data-testid="vehicle-error-${cameraA.id}"]`).text()).toBe(
      "Description too long.",
    );
  });

  it("falls back to a generic save error for non-API failures", async () => {
    mockedPutVehicle.mockRejectedValue(new TypeError("down"));
    const wrapper = await mountWithThreePoints();
    await wrapper.find(`[data-testid="vehicle-description-${cameraA.id}"]`).setValue("My car");
    await wrapper.find(`[data-testid="save-vehicle-${cameraA.id}"]`).trigger("click");
    await flushPromises();
    expect(wrapper.find(`[data-testid="vehicle-error-${cameraA.id}"]`).text()).toBe(
      "Unexpected error.",
    );
  });

  it("toggles enabled on a saved vehicle and saves the change", async () => {
    mockedCameras.mockResolvedValue([cameraA]);
    mockedGetVehicle.mockResolvedValue(savedVehicle);
    mockedPutVehicle.mockResolvedValue({ ...savedVehicle, enabled: false });
    const wrapper = mountPanel();
    await flushPromises();

    const toggle = wrapper.findComponent(ToggleSwitch);
    await toggle.vm.$emit("update:modelValue", false);
    await wrapper.find(`[data-testid="save-vehicle-${cameraA.id}"]`).trigger("click");
    await flushPromises();

    expect(mockedPutVehicle).toHaveBeenCalledWith(
      cameraA.id,
      expect.objectContaining({ enabled: false }),
    );
  });

  it("saves updated length/threshold/enabled values", async () => {
    mockedPutVehicle.mockResolvedValue(savedVehicle);
    const wrapper = await mountWithThreePoints();
    await wrapper.find(`[data-testid="vehicle-description-${cameraA.id}"]`).setValue("My car");

    const lengthInput = wrapper.find(`[data-testid="vehicle-length-${cameraA.id}"] input`);
    await lengthInput.setValue("18");
    await lengthInput.trigger("blur");
    const thresholdInput = wrapper.find(`[data-testid="vehicle-threshold-${cameraA.id}"] input`);
    await thresholdInput.setValue("4");
    await thresholdInput.trigger("blur");

    await wrapper.find(`[data-testid="save-vehicle-${cameraA.id}"]`).trigger("click");
    await flushPromises();
    expect(mockedPutVehicle).toHaveBeenCalledWith(
      cameraA.id,
      expect.objectContaining({ estimated_length_feet: 18, distance_threshold_feet: 4 }),
    );
  });
});

describe("SettingsVehiclesPanel deleting", () => {
  beforeEach(() => {
    mockedCameras.mockResolvedValue([cameraA]);
    mockedGetVehicle.mockResolvedValue(savedVehicle);
  });

  it("asks for confirmation before deleting", async () => {
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find(`[data-testid="delete-vehicle-${cameraA.id}"]`).trigger("click");
    expect(confirmRequire).toHaveBeenCalledWith(
      expect.objectContaining({ header: "Remove vehicle protection" }),
    );
    expect(mockedDeleteVehicle).not.toHaveBeenCalled();
  });

  it("deletes on confirmation, resetting the form but keeping the reference frame", async () => {
    mockedDeleteVehicle.mockResolvedValue(undefined);
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find(`[data-testid="delete-vehicle-${cameraA.id}"]`).trigger("click");
    const options = confirmRequire.mock.calls.at(-1)?.[0] as { accept: () => void };
    options.accept();
    await flushPromises();

    expect(mockedDeleteVehicle).toHaveBeenCalledWith(cameraA.id);
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ summary: "Vehicle protection removed" }),
    );
    expect(wrapper.find(`[data-testid="delete-vehicle-${cameraA.id}"]`).exists()).toBe(false);
    expect(wrapper.find(`[data-testid="outline-svg-${cameraA.id}"]`).exists()).toBe(true);
    expect(wrapper.findAll(`[data-testid^="outline-point-${cameraA.id}-"]`)).toHaveLength(0);
  });

  it("toasts the API error message when deletion fails", async () => {
    mockedDeleteVehicle.mockRejectedValue(new ApiError(500, "Server exploded"));
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find(`[data-testid="delete-vehicle-${cameraA.id}"]`).trigger("click");
    const options = confirmRequire.mock.calls.at(-1)?.[0] as { accept: () => void };
    options.accept();
    await flushPromises();
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "error", detail: "Server exploded" }),
    );
  });

  it("toasts a generic error for a non-API deletion failure", async () => {
    mockedDeleteVehicle.mockRejectedValue(new TypeError("down"));
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find(`[data-testid="delete-vehicle-${cameraA.id}"]`).trigger("click");
    const options = confirmRequire.mock.calls.at(-1)?.[0] as { accept: () => void };
    options.accept();
    await flushPromises();
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "error", detail: "Unexpected error." }),
    );
  });
});
