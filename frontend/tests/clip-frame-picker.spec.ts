import { flushPromises, mount } from "@vue/test-utils";
import Slider from "primevue/slider";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  detectFacesInClipFrame: vi.fn(),
}));

import { detectFacesInClipFrame } from "@/api";
import { ApiError } from "@/api/client";
import ClipFramePicker from "@/components/ClipFramePicker.vue";
import { makePinia, mountGlobal } from "./helpers";

import type { DetectedFaceRead } from "@/api";

const mockedDetect = vi.mocked(detectFacesInClipFrame);

function mountPicker(clipId = "clip-1", durationSeconds: number | null = 10) {
  return mount(ClipFramePicker, {
    props: { clipId, durationSeconds },
    global: mountGlobal(makePinia()),
    attachTo: document.body,
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  mockedDetect.mockResolvedValue([]);
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("ClipFramePicker", () => {
  it("shows the frame image and detects faces at the clip's midpoint", async () => {
    mountPicker("clip-1", 10);
    await flushPromises();
    expect(mockedDetect).toHaveBeenCalledWith("clip-1", 5);
    const img = document.body.querySelector<HTMLImageElement>('[data-testid="picker-frame-image"]');
    expect(img?.src).toContain("/api/biometrics/clips/clip-1/frame?frame_seconds=5");
  });

  it("falls back to a 10s assumed duration when the clip's duration is unknown", async () => {
    const wrapper = mountPicker("clip-1", null);
    await flushPromises();
    expect(mockedDetect).toHaveBeenCalledWith("clip-1", 5);
    const slider = wrapper.findComponent(Slider);
    expect(slider.props("max")).toBe(10);
  });

  it("re-runs detection and resets the selection when the clip id changes", async () => {
    const wrapper = mountPicker("clip-1", 10);
    await flushPromises();
    mockedDetect.mockClear();

    await wrapper.setProps({ clipId: "clip-2", durationSeconds: 20 });
    await flushPromises();
    expect(mockedDetect).toHaveBeenCalledWith("clip-2", 10);
  });

  it("shows a detecting message while the request is pending", async () => {
    let resolveDetect!: (faces: DetectedFaceRead[]) => void;
    mockedDetect.mockReturnValue(
      new Promise((resolve) => {
        resolveDetect = resolve;
      }),
    );
    mountPicker();
    await Promise.resolve();
    expect(document.body.querySelector('[data-testid="picker-detecting"]')).toBeTruthy();

    resolveDetect([]);
    await flushPromises();
    expect(document.body.querySelector('[data-testid="picker-detecting"]')).toBeNull();
  });

  it("shows a no-faces message when detection finds nothing", async () => {
    mockedDetect.mockResolvedValue([]);
    mountPicker();
    await flushPromises();
    expect(document.body.querySelector('[data-testid="picker-no-faces"]')).toBeTruthy();
  });

  it("shows the detection error message", async () => {
    mockedDetect.mockRejectedValue(new ApiError(409, "Clip has no downloaded file."));
    mountPicker();
    await flushPromises();
    expect(document.body.textContent).toContain("Clip has no downloaded file.");
  });

  it("falls back to a generic detection error for non-API failures", async () => {
    mockedDetect.mockRejectedValue(new TypeError("down"));
    mountPicker();
    await flushPromises();
    expect(document.body.textContent).toContain("Could not detect faces in this frame.");
  });

  it("renders a positioned box per detected face, toggles selected state, and emits the selection", async () => {
    mockedDetect.mockResolvedValue([
      { bbox: [0.1, 0.2, 0.3, 0.4], confidence: 0.9 },
      { bbox: [0.5, 0.5, 0.2, 0.2], confidence: 0.8 },
    ]);
    const wrapper = mountPicker();
    await flushPromises();

    const box0 = document.body.querySelector<HTMLElement>('[data-testid="picker-face-box-0"]')!;
    expect(box0.style.left).toBe("10%");
    expect(box0.style.top).toBe("20%");
    expect(box0.style.width).toBe("30%");
    expect(box0.style.height).toBe("40%");
    expect(box0.className).not.toContain("selected");

    box0.click();
    await flushPromises();
    expect(box0.className).toContain("selected");
    const emitted = wrapper.emitted("selection-change");
    expect(emitted).toBeTruthy();
    expect(emitted![emitted!.length - 1]).toEqual([
      { frameSeconds: 5, face: { bbox: [0.1, 0.2, 0.3, 0.4], confidence: 0.9 } },
    ]);
  });

  it("emits null when a new frame is loaded, clearing any prior selection", async () => {
    mockedDetect.mockResolvedValue([{ bbox: [0, 0, 0.1, 0.1], confidence: 0.9 }]);
    const wrapper = mountPicker();
    await flushPromises();
    document.body.querySelector<HTMLElement>('[data-testid="picker-face-box-0"]')?.click();
    await flushPromises();
    expect(wrapper.emitted("selection-change")!.at(-1)).not.toEqual([null]);

    const slider = wrapper.findComponent(Slider);
    await slider.vm.$emit("update:modelValue", 7.5);
    await slider.vm.$emit("change", 7.5);
    await flushPromises();

    expect(mockedDetect).toHaveBeenCalledWith("clip-1", 7.5);
    expect(wrapper.emitted("selection-change")!.at(-1)).toEqual([null]);
  });
});
