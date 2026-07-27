import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
import PersonEnrollmentPanel from "@/components/PersonEnrollmentPanel.vue";
import { makePinia, mountGlobal } from "./helpers";

import type { CameraRead, ClipRead } from "@/api";

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
    storage_backend: "local",
    recognized_people: [],
    ...overrides,
  };
}

async function mountPanel(personId = "p-1") {
  const wrapper = mount(PersonEnrollmentPanel, {
    props: { personId },
    global: mountGlobal(makePinia()),
    attachTo: document.body,
  });
  await flushPromises();
  return wrapper;
}

async function selectCamera(wrapper: Awaited<ReturnType<typeof mountPanel>>): Promise<void> {
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

describe("PersonEnrollmentPanel setup", () => {
  it("loads cameras on mount", async () => {
    await mountPanel();
    expect(mockedCameras).toHaveBeenCalledTimes(1);
  });

  it("shows the camera load error message", async () => {
    mockedCameras.mockRejectedValue(new ApiError(500, "Server exploded"));
    await mountPanel();
    expect(document.body.textContent).toContain("Server exploded");
  });

  it("falls back to a generic camera load error for non-API failures", async () => {
    mockedCameras.mockRejectedValue(new TypeError("down"));
    await mountPanel();
    expect(document.body.textContent).toContain("Could not load cameras.");
  });
});

describe("PersonEnrollmentPanel clip picking", () => {
  it("loads clips for the chosen camera within the default 24h range", async () => {
    const wrapper = await mountPanel();
    await selectCamera(wrapper);
    expect(mockedClips).toHaveBeenCalledWith(
      expect.objectContaining({ camera_id: "cam-1", downloaded_only: true, page_size: 50 }),
    );
    const call = mockedClips.mock.calls[0]![0]!;
    expect(call.since).toBeDefined();
  });

  it("sends no since filter for the All time option", async () => {
    const wrapper = await mountPanel();
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
    const wrapper = await mountPanel();
    await selectCamera(wrapper);
    expect(document.body.querySelector('[data-testid="enroll-clips-loading"]')).toBeTruthy();

    resolveClips({ items: [makeClip()], total: 1, page: 1, page_size: 50 });
    await flushPromises();
    expect(document.body.querySelector('[data-testid="enroll-clip-clip-1"]')).toBeTruthy();
  });

  it("shows the clips load error message", async () => {
    mockedClips.mockRejectedValue(new ApiError(500, "Server exploded"));
    const wrapper = await mountPanel();
    await selectCamera(wrapper);
    expect(document.body.textContent).toContain("Server exploded");
  });

  it("falls back to a generic clips load error for non-API failures", async () => {
    mockedClips.mockRejectedValue(new TypeError("down"));
    const wrapper = await mountPanel();
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
    const wrapper = await mountPanel();
    await selectCamera(wrapper);
    const item = document.body.querySelector('[data-testid="enroll-clip-clip-1"]')!;
    expect(item.querySelector("img")).toBeNull();
    expect(item.querySelector(".pi-video")).toBeTruthy();
  });

  it("shows an empty message when no clips are downloaded in range", async () => {
    const wrapper = await mountPanel();
    await selectCamera(wrapper);
    expect(document.body.textContent).toContain("No downloaded clips");
  });

  it("clears the clip list when the camera is unselected", async () => {
    mockedClips.mockResolvedValue({ items: [makeClip()], total: 1, page: 1, page_size: 50 });
    const wrapper = await mountPanel();
    await selectCamera(wrapper);
    expect(document.body.querySelector('[data-testid="enroll-clip-clip-1"]')).toBeTruthy();

    await wrapper.findComponent({ name: "Select" }).vm.$emit("update:modelValue", null);
    await flushPromises();
    expect(document.body.querySelector('[data-testid="enroll-clip-list"]')).toBeNull();
  });

  it("renders the frame picker once a clip is picked", async () => {
    mockedClips.mockResolvedValue({
      items: [makeClip({ duration_seconds: 10 })],
      total: 1,
      page: 1,
      page_size: 50,
    });
    const wrapper = await mountPanel();
    await selectCamera(wrapper);
    await selectClip("clip-1");
    expect(mockedDetect).toHaveBeenCalledWith("clip-1", 5);
    expect(document.body.querySelector('[data-testid="picker-frame-image"]')).toBeTruthy();
  });
});

describe("PersonEnrollmentPanel enrollment", () => {
  async function openWithOneDetectedFace() {
    mockedClips.mockResolvedValue({ items: [makeClip()], total: 1, page: 1, page_size: 50 });
    mockedDetect.mockResolvedValue([{ bbox: [0.1, 0.1, 0.2, 0.2], confidence: 0.9 }]);
    const wrapper = await mountPanel("p-1");
    await selectCamera(wrapper);
    await selectClip("clip-1");
    document.body.querySelector<HTMLElement>('[data-testid="picker-face-box-0"]')?.click();
    await flushPromises();
    return wrapper;
  }

  it("disables Enroll until a face is selected", async () => {
    mockedClips.mockResolvedValue({ items: [makeClip()], total: 1, page: 1, page_size: 50 });
    mockedDetect.mockResolvedValue([{ bbox: [0.1, 0.1, 0.2, 0.2], confidence: 0.9 }]);
    const wrapper = await mountPanel();
    await selectCamera(wrapper);
    await selectClip("clip-1");
    const confirm = document.body.querySelector<HTMLButtonElement>('[data-testid="enroll-confirm"]');
    expect(confirm?.disabled).toBe(true);
  });

  it("submits the clip id, frame time, and selected bbox, then shows a success message", async () => {
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
    expect(document.body.querySelector('[data-testid="enroll-success"]')).toBeTruthy();
    // Ready to enroll another sample immediately after.
    const confirm = document.body.querySelector<HTMLButtonElement>('[data-testid="enroll-confirm"]');
    expect(confirm?.disabled).toBe(true);
  });

  it("shows the API error message when enrollment fails", async () => {
    mockedEnroll.mockRejectedValue(new ApiError(404, "No detected face matches that selection."));
    await openWithOneDetectedFace();

    document.body.querySelector<HTMLElement>('[data-testid="enroll-confirm"]')?.click();
    await flushPromises();

    expect(document.body.textContent).toContain("No detected face matches that selection.");
    expect(document.body.querySelector('[data-testid="enroll-success"]')).toBeNull();
  });

  it("falls back to a generic error for a non-API enrollment failure", async () => {
    mockedEnroll.mockRejectedValue(new TypeError("down"));
    await openWithOneDetectedFace();
    document.body.querySelector<HTMLElement>('[data-testid="enroll-confirm"]')?.click();
    await flushPromises();
    expect(document.body.textContent).toContain("Could not enroll this face.");
  });
});
