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

// Matches ClipFramePicker's FACE_DETECTION_DEBOUNCE_MS with margin. Real
// timers, not vi.useFakeTimers() - PrimeVue components schedule their own
// internal setTimeouts that fake-timer control doesn't know to advance,
// a known source of flakiness in this codebase's other specs.
async function waitForDebounce(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 260));
}

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

    // PrimeVue's Slider always emits update:modelValue and change together,
    // synchronously, from the same internal updateModel() call.
    const slider = wrapper.findComponent(Slider);
    await slider.vm.$emit("update:modelValue", 7.5);
    await slider.vm.$emit("change", 7.5);
    // Clearing the prior selection is immediate - it doesn't wait for the
    // debounced detection call below.
    expect(wrapper.emitted("selection-change")!.at(-1)).toEqual([null]);
    await waitForDebounce();

    expect(mockedDetect).toHaveBeenCalledWith("clip-1", 7.5);
  });

  it("debounces rapid scrubbing into a single detect-faces call for the final position", async () => {
    mockedDetect.mockResolvedValue([]);
    const wrapper = mountPicker();
    await flushPromises();
    mockedDetect.mockClear();

    const slider = wrapper.findComponent(Slider);
    // A drag fires `change` on every mousemove tick, not just once at
    // release - simulate a burst of ticks landing on different positions.
    for (const value of [1, 2, 3, 4, 5]) {
      await slider.vm.$emit("update:modelValue", value);
      await slider.vm.$emit("change", value);
    }
    await waitForDebounce();

    expect(mockedDetect).toHaveBeenCalledTimes(1);
    expect(mockedDetect).toHaveBeenCalledWith("clip-1", 5);
  });

  it("discards a stale response that resolves after a newer request has already started", async () => {
    const wrapper = mountPicker();
    await flushPromises();
    mockedDetect.mockClear();

    let resolveFirst!: (faces: DetectedFaceRead[]) => void;
    mockedDetect.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveFirst = resolve;
        }),
    );
    const slider = wrapper.findComponent(Slider);
    await slider.vm.$emit("update:modelValue", 3);
    await slider.vm.$emit("change", 3);
    await waitForDebounce();
    expect(mockedDetect).toHaveBeenCalledWith("clip-1", 3);

    // A second, faster-resolving request starts (and finishes) before the
    // first one's slow response arrives.
    mockedDetect.mockResolvedValueOnce([{ bbox: [0.2, 0.2, 0.1, 0.1], confidence: 0.7 }]);
    await slider.vm.$emit("update:modelValue", 6);
    await slider.vm.$emit("change", 6);
    await waitForDebounce();
    expect(mockedDetect).toHaveBeenCalledWith("clip-1", 6);
    expect(
      document.body.querySelector<HTMLElement>('[data-testid="picker-face-box-0"]')?.style.left,
    ).toBe("20%");

    // The stale first call finally resolves - it must not clobber the
    // second (newer) call's already-applied result.
    resolveFirst([{ bbox: [0.9, 0.9, 0.05, 0.05], confidence: 0.5 }]);
    await flushPromises();

    const box = document.body.querySelector<HTMLElement>('[data-testid="picker-face-box-0"]');
    expect(box?.style.left).toBe("20%");
  });

  it("discards a stale rejection that arrives after a newer request has already succeeded", async () => {
    const wrapper = mountPicker();
    await flushPromises();
    mockedDetect.mockClear();

    let rejectFirst!: (error: unknown) => void;
    mockedDetect.mockImplementationOnce(
      () =>
        new Promise((_resolve, reject) => {
          rejectFirst = reject;
        }),
    );
    const slider = wrapper.findComponent(Slider);
    await slider.vm.$emit("update:modelValue", 3);
    await slider.vm.$emit("change", 3);
    await waitForDebounce();

    mockedDetect.mockResolvedValueOnce([{ bbox: [0.2, 0.2, 0.1, 0.1], confidence: 0.7 }]);
    await slider.vm.$emit("update:modelValue", 6);
    await slider.vm.$emit("change", 6);
    await waitForDebounce();
    expect(document.body.querySelector('[data-testid="picker-face-box-0"]')).toBeTruthy();
    expect(document.body.querySelector('[data-testid="picker-detecting"]')).toBeNull();

    // The stale first call finally rejects - it must not overwrite the
    // second (newer) call's already-applied success state with an error.
    rejectFirst(new ApiError(409, "Clip has no downloaded file."));
    await flushPromises();

    expect(document.body.textContent).not.toContain("Clip has no downloaded file.");
    expect(document.body.querySelector('[data-testid="picker-face-box-0"]')).toBeTruthy();
  });

  it("cancels a pending debounced detection when the clip id changes mid-scrub", async () => {
    const wrapper = mountPicker("clip-1", 10);
    await flushPromises();
    mockedDetect.mockClear();

    const slider = wrapper.findComponent(Slider);
    await slider.vm.$emit("update:modelValue", 3);
    await slider.vm.$emit("change", 3);
    // Switch clips before the debounce for the value-3 scrub would fire.
    await wrapper.setProps({ clipId: "clip-2", durationSeconds: 20 });
    await flushPromises();
    await waitForDebounce();

    expect(mockedDetect).not.toHaveBeenCalledWith("clip-1", 3);
    expect(mockedDetect).toHaveBeenCalledWith("clip-2", 10);
  });

  it("cancels a pending debounced detection on unmount", async () => {
    const wrapper = mountPicker();
    await flushPromises();
    mockedDetect.mockClear();

    const slider = wrapper.findComponent(Slider);
    await slider.vm.$emit("update:modelValue", 3);
    await slider.vm.$emit("change", 3);
    wrapper.unmount();
    await waitForDebounce();

    expect(mockedDetect).not.toHaveBeenCalled();
  });
});
