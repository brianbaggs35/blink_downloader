import { flushPromises, mount } from "@vue/test-utils";
import Slider from "primevue/slider";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  listCameras: vi.fn(),
  listClips: vi.fn(),
  detectFacesInClipFrame: vi.fn(),
  enrollFace: vi.fn(),
}));

import {
  detectFacesInClipFrame,
  enrollFace,
  listCameras,
  listClips,
} from "@/api";
import { ApiError } from "@/api/client";
import EnrollFaceDialog from "@/components/EnrollFaceDialog.vue";
import { makePinia, mountGlobal } from "./helpers";

import type { CameraRead, ClipRead, DetectedFaceRead } from "@/api";

const mockedCameras = vi.mocked(listCameras);
const mockedClips = vi.mocked(listClips);
const mockedDetect = vi.mocked(detectFacesInClipFrame);
const mockedEnroll = vi.mocked(enrollFace);

const cameraA: CameraRead = {
  id: "cam-1",
  name: "Front Door",
  camera_type: "outdoor",
  enabled: true,
  battery: "ok",
  last_synced_at: null,
  security_context: null,
};

function makeClip(overrides: Partial<ClipRead> = {}): ClipRead {
  return {
    id: "clip-1",
    camera_id: "cam-1",
    recorded_at: "2026-07-25T18:30:00Z",
    duration_seconds: 10,
    file_size_bytes: 1024,
    downloaded_at: "2026-07-25T18:31:00Z",
    deleted_on_blink: false,
    thumbnail_generated: true,
    recognized_people: [],
    ...overrides,
  };
}

function mountDialog(personId: string | null, personName = "Alex") {
  return mount(EnrollFaceDialog, {
    props: { personId, personName },
    global: mountGlobal(makePinia()),
    attachTo: document.body,
  });
}

async function mountOpen(personId = "p-1", personName = "Alex") {
  const wrapper = mountDialog(personId, personName);
  await nextTick();
  await flushPromises();
  return wrapper;
}

async function selectCamera(wrapper: Awaited<ReturnType<typeof mountOpen>>): Promise<void> {
  await wrapper.findComponent({ name: "Select" }).vm.$emit("update:modelValue", "cam-1");
  await flushPromises();
}

async function selectClip(clipId: string): Promise<void> {
  document.body.querySelector<HTMLElement>(`[data-testid="enroll-clip-${clipId}"]`)?.click();
  await flushPromises();
}

beforeEach(() => {
  vi.clearAllMocks();
  mockedCameras.mockResolvedValue([cameraA]);
  mockedClips.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 50 });
  mockedDetect.mockResolvedValue([]);
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("EnrollFaceDialog visibility and setup", () => {
  it("is not visible when personId is null", async () => {
    mountDialog(null);
    await nextTick();
    expect(document.body.querySelector('[data-testid="enroll-dialog"]')).toBeNull();
  });

  it("shows the header with the target person's name and loads cameras", async () => {
    await mountOpen("p-1", "Jordan");
    expect(document.body.textContent).toContain("Enroll a face for Jordan");
    expect(mockedCameras).toHaveBeenCalledTimes(1);
  });

  it("shows the camera load error message", async () => {
    mockedCameras.mockRejectedValue(new ApiError(500, "Server exploded"));
    await mountOpen();
    expect(document.body.textContent).toContain("Server exploded");
  });

  it("falls back to a generic camera load error for non-API failures", async () => {
    mockedCameras.mockRejectedValue(new TypeError("down"));
    await mountOpen();
    expect(document.body.textContent).toContain("Could not load cameras.");
  });

  it("emits close when the dialog reports it was dismissed", async () => {
    const wrapper = await mountOpen();
    await wrapper.findComponent({ name: "Dialog" }).vm.$emit("update:visible", false);
    expect(wrapper.emitted("close")).toHaveLength(1);
  });

  it("does not emit close when the dialog's visible model turns true", async () => {
    const wrapper = await mountOpen();
    await wrapper.findComponent({ name: "Dialog" }).vm.$emit("update:visible", true);
    expect(wrapper.emitted("close")).toBeUndefined();
  });

  it("does not re-fetch cameras on a second person, but does reset the session", async () => {
    const wrapper = await mountOpen("p-1", "Alex");
    await selectCamera(wrapper);
    expect(document.body.querySelector('[data-testid="enroll-camera-select"]')).toBeTruthy();

    await wrapper.setProps({ personId: "p-2", personName: "Sam" });
    await flushPromises();

    expect(mockedCameras).toHaveBeenCalledTimes(1);
    expect(document.body.textContent).toContain("Enroll a face for Sam");
    // Resetting clears the picked camera, so the clip-picking step is hidden again.
    expect(document.body.querySelector('[data-testid="enroll-clip-list"]')).toBeNull();
  });

  it("does nothing when personId is set to null (dialog closing)", async () => {
    const wrapper = await mountOpen("p-1", "Alex");
    await wrapper.setProps({ personId: null });
    await flushPromises();
    expect(mockedCameras).toHaveBeenCalledTimes(1);
  });
});

describe("EnrollFaceDialog clip picking", () => {
  it("loads clips for the chosen camera within the default 24h range", async () => {
    const wrapper = await mountOpen();
    await selectCamera(wrapper);
    expect(mockedClips).toHaveBeenCalledWith(
      expect.objectContaining({ camera_id: "cam-1", downloaded_only: true, page_size: 50 }),
    );
    const call = mockedClips.mock.calls[0]![0]!;
    expect(call.since).toBeDefined();
  });

  it("sends no since filter for the All time option", async () => {
    const wrapper = await mountOpen();
    await selectCamera(wrapper);
    const selectButton = wrapper.findComponent({ name: "SelectButton" });
    await selectButton.vm.$emit("update:modelValue", { label: "All time", hours: null });
    await flushPromises();
    expect(mockedClips).toHaveBeenLastCalledWith(expect.objectContaining({ since: undefined }));
  });

  it("shows a clips loading skeleton, then the list", async () => {
    let resolveClips!: (value: { items: ClipRead[]; total: number; page: number; page_size: number }) => void;
    mockedClips.mockReturnValue(
      new Promise((resolve) => {
        resolveClips = resolve;
      }),
    );
    const wrapper = await mountOpen();
    await wrapper.findComponent({ name: "Select" }).vm.$emit("update:modelValue", "cam-1");
    await nextTick();
    expect(document.body.querySelector('[data-testid="enroll-clips-loading"]')).toBeTruthy();

    resolveClips({ items: [makeClip()], total: 1, page: 1, page_size: 50 });
    await flushPromises();
    expect(document.body.querySelector('[data-testid="enroll-clip-clip-1"]')).toBeTruthy();
  });

  it("shows the clips load error message", async () => {
    mockedClips.mockRejectedValue(new ApiError(500, "Server exploded"));
    const wrapper = await mountOpen();
    await selectCamera(wrapper);
    expect(document.body.textContent).toContain("Server exploded");
  });

  it("falls back to a generic clips load error for non-API failures", async () => {
    mockedClips.mockRejectedValue(new TypeError("down"));
    const wrapper = await mountOpen();
    await selectCamera(wrapper);
    expect(document.body.textContent).toContain("Could not load clips.");
  });

  it("falls back to a placeholder thumbnail for a clip with none generated yet", async () => {
    mockedClips.mockResolvedValue({
      items: [makeClip({ thumbnail_generated: false })],
      total: 1,
      page: 1,
      page_size: 50,
    });
    const wrapper = await mountOpen();
    await selectCamera(wrapper);
    const item = document.body.querySelector('[data-testid="enroll-clip-clip-1"]')!;
    expect(item.querySelector("img")).toBeNull();
    expect(item.querySelector(".pi-video")).toBeTruthy();
  });

  it("shows an empty message when no clips are downloaded in range", async () => {
    const wrapper = await mountOpen();
    await selectCamera(wrapper);
    expect(document.body.textContent).toContain("No downloaded clips");
  });

  it("clears the clip list when the camera is unselected", async () => {
    mockedClips.mockResolvedValue({ items: [makeClip()], total: 1, page: 1, page_size: 50 });
    const wrapper = await mountOpen();
    await selectCamera(wrapper);
    expect(document.body.querySelector('[data-testid="enroll-clip-clip-1"]')).toBeTruthy();

    await wrapper.findComponent({ name: "Select" }).vm.$emit("update:modelValue", null);
    await flushPromises();
    expect(document.body.querySelector('[data-testid="enroll-clip-list"]')).toBeNull();
  });
});

describe("EnrollFaceDialog frame + face detection", () => {
  async function openWithOneClip() {
    mockedClips.mockResolvedValue({ items: [makeClip({ duration_seconds: 10 })], total: 1, page: 1, page_size: 50 });
    const wrapper = await mountOpen();
    await selectCamera(wrapper);
    return wrapper;
  }

  it("shows the frame image and detects faces at the clip's midpoint", async () => {
    await openWithOneClip();
    await selectClip("clip-1");
    expect(mockedDetect).toHaveBeenCalledWith("clip-1", 5);
    const img = document.body.querySelector<HTMLImageElement>('[data-testid="enroll-frame-image"]');
    expect(img?.src).toContain("/api/biometrics/clips/clip-1/frame?frame_seconds=5");
  });

  it("falls back to a 10s assumed duration when a clip's duration is unknown", async () => {
    mockedClips.mockResolvedValue({
      items: [makeClip({ duration_seconds: null })],
      total: 1,
      page: 1,
      page_size: 50,
    });
    const wrapper = await mountOpen();
    await selectCamera(wrapper);
    await selectClip("clip-1");
    expect(mockedDetect).toHaveBeenCalledWith("clip-1", 5);
    const slider = wrapper.findComponent(Slider);
    expect(slider.props("max")).toBe(10);
  });

  it("shows a detecting message while the request is pending", async () => {
    let resolveDetect!: (faces: DetectedFaceRead[]) => void;
    mockedDetect.mockReturnValue(
      new Promise((resolve) => {
        resolveDetect = resolve;
      }),
    );
    await openWithOneClip();
    document.body.querySelector<HTMLElement>('[data-testid="enroll-clip-clip-1"]')?.click();
    await nextTick();
    expect(document.body.querySelector('[data-testid="enroll-detecting"]')).toBeTruthy();

    resolveDetect([]);
    await flushPromises();
    expect(document.body.querySelector('[data-testid="enroll-detecting"]')).toBeNull();
  });

  it("shows a no-faces message when detection finds nothing", async () => {
    mockedDetect.mockResolvedValue([]);
    await openWithOneClip();
    await selectClip("clip-1");
    expect(document.body.querySelector('[data-testid="enroll-no-faces"]')).toBeTruthy();
  });

  it("shows the detection error message", async () => {
    mockedDetect.mockRejectedValue(new ApiError(409, "Clip has no downloaded file."));
    await openWithOneClip();
    await selectClip("clip-1");
    expect(document.body.textContent).toContain("Clip has no downloaded file.");
  });

  it("falls back to a generic detection error for non-API failures", async () => {
    mockedDetect.mockRejectedValue(new TypeError("down"));
    await openWithOneClip();
    await selectClip("clip-1");
    expect(document.body.textContent).toContain("Could not detect faces in this frame.");
  });

  it("renders a positioned box per detected face and a selectable state on click", async () => {
    mockedDetect.mockResolvedValue([
      { bbox: [0.1, 0.2, 0.3, 0.4], confidence: 0.9 },
      { bbox: [0.5, 0.5, 0.2, 0.2], confidence: 0.8 },
    ]);
    await openWithOneClip();
    await selectClip("clip-1");

    const box0 = document.body.querySelector<HTMLElement>('[data-testid="enroll-face-box-0"]')!;
    expect(box0.style.left).toBe("10%");
    expect(box0.style.top).toBe("20%");
    expect(box0.style.width).toBe("30%");
    expect(box0.style.height).toBe("40%");
    expect(box0.className).not.toContain("selected");

    box0.click();
    await nextTick();
    expect(box0.className).toContain("selected");
    const confirm = document.body.querySelector<HTMLButtonElement>('[data-testid="enroll-confirm"]');
    expect(confirm?.disabled).toBe(false);
  });

  it("re-detects when the scrubber's value is committed", async () => {
    mockedDetect.mockResolvedValue([{ bbox: [0, 0, 0.1, 0.1], confidence: 0.9 }]);
    const wrapper = await openWithOneClip();
    await selectClip("clip-1");
    mockedDetect.mockClear();

    const slider = wrapper.findComponent(Slider);
    await slider.vm.$emit("update:modelValue", 7.5);
    await slider.vm.$emit("change", 7.5);
    await flushPromises();

    expect(mockedDetect).toHaveBeenCalledWith("clip-1", 7.5);
  });
});

describe("EnrollFaceDialog enrollment", () => {
  async function openWithOneDetectedFace() {
    mockedClips.mockResolvedValue({ items: [makeClip()], total: 1, page: 1, page_size: 50 });
    mockedDetect.mockResolvedValue([{ bbox: [0.1, 0.1, 0.2, 0.2], confidence: 0.9 }]);
    const wrapper = await mountOpen("p-1", "Alex");
    await selectCamera(wrapper);
    await selectClip("clip-1");
    document.body.querySelector<HTMLElement>('[data-testid="enroll-face-box-0"]')?.click();
    await nextTick();
    return wrapper;
  }

  it("disables Enroll until a face is selected", async () => {
    mockedClips.mockResolvedValue({ items: [makeClip()], total: 1, page: 1, page_size: 50 });
    mockedDetect.mockResolvedValue([{ bbox: [0.1, 0.1, 0.2, 0.2], confidence: 0.9 }]);
    const wrapper = await mountOpen();
    await selectCamera(wrapper);
    await selectClip("clip-1");
    const confirm = document.body.querySelector<HTMLButtonElement>('[data-testid="enroll-confirm"]');
    expect(confirm?.disabled).toBe(true);
  });

  it("submits the clip id, frame time, and selected bbox, then emits enrolled and closes", async () => {
    mockedEnroll.mockResolvedValue({
      id: "face-1",
      source_clip_id: "clip-1",
      source_frame_seconds: 5,
      created_at: "2026-07-25T00:00:00Z",
    });
    const wrapper = await openWithOneDetectedFace();

    document.body.querySelector<HTMLElement>('[data-testid="enroll-confirm"]')?.click();
    await flushPromises();

    expect(mockedEnroll).toHaveBeenCalledWith("p-1", {
      clip_id: "clip-1",
      frame_seconds: 5,
      bbox: [0.1, 0.1, 0.2, 0.2],
    });
    expect(wrapper.emitted("enrolled")).toHaveLength(1);
    // Visibility is derived from the personId prop, owned by the parent —
    // this only proves the component's own intent to close; a parent
    // reacting to @close (BiometricsView does) is what actually hides it.
    expect(wrapper.emitted("close")).toHaveLength(1);
  });

  it("shows the API error message when enrollment fails and stays open", async () => {
    mockedEnroll.mockRejectedValue(new ApiError(404, "No detected face matches that selection."));
    const wrapper = await openWithOneDetectedFace();

    document.body.querySelector<HTMLElement>('[data-testid="enroll-confirm"]')?.click();
    await flushPromises();

    expect(document.body.textContent).toContain("No detected face matches that selection.");
    expect(wrapper.emitted("enrolled")).toBeUndefined();
  });

  it("falls back to a generic error for a non-API enrollment failure", async () => {
    mockedEnroll.mockRejectedValue(new TypeError("down"));
    await openWithOneDetectedFace();
    document.body.querySelector<HTMLElement>('[data-testid="enroll-confirm"]')?.click();
    await flushPromises();
    expect(document.body.textContent).toContain("Could not enroll this face.");
  });

  it("closes via the Cancel button", async () => {
    const wrapper = await openWithOneDetectedFace();
    const buttons = [...document.body.querySelectorAll("button")];
    const cancel = buttons.find((b) => b.textContent?.trim() === "Cancel");
    cancel?.click();
    await flushPromises();
    expect(wrapper.emitted("close")).toHaveLength(1);
  });
});
