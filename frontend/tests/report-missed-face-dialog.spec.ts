import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  listPeople: vi.fn(),
  createPerson: vi.fn(),
  enrollFace: vi.fn(),
  detectFacesInClipFrame: vi.fn(),
}));

import { createPerson, detectFacesInClipFrame, enrollFace, listPeople } from "@/api";
import { ApiError } from "@/api/client";
import ReportMissedFaceDialog from "@/components/ReportMissedFaceDialog.vue";
import { makePinia, mountGlobal } from "./helpers";

import type { PersonRead } from "@/api";

const mockedListPeople = vi.mocked(listPeople);
const mockedCreatePerson = vi.mocked(createPerson);
const mockedEnrollFace = vi.mocked(enrollFace);
const mockedDetectFaces = vi.mocked(detectFacesInClipFrame);

function makePerson(overrides: Partial<PersonRead> = {}): PersonRead {
  return {
    id: "p-1",
    name: "Alex",
    has_thumbnail: false,
    face_count: 1,
    created_at: "2026-07-20T00:00:00Z",
    updated_at: "2026-07-20T00:00:00Z",
    ...overrides,
  };
}

function mountDialog(clipId: string | null, durationSeconds: number | null = 10) {
  return mount(ReportMissedFaceDialog, {
    props: { clipId, durationSeconds },
    global: mountGlobal(makePinia()),
    attachTo: document.body,
  });
}

async function mountOpen(clipId = "clip-1", durationSeconds: number | null = 10) {
  const wrapper = mountDialog(clipId, durationSeconds);
  await nextTick();
  await flushPromises();
  return wrapper;
}

async function pickAFace(): Promise<void> {
  document.body.querySelector<HTMLElement>('[data-testid="picker-face-box-0"]')?.click();
  await flushPromises();
}

beforeEach(() => {
  vi.clearAllMocks();
  mockedListPeople.mockResolvedValue([makePerson()]);
  mockedDetectFaces.mockResolvedValue([{ bbox: [0.1, 0.1, 0.2, 0.2], confidence: 0.9 }]);
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("ReportMissedFaceDialog visibility and setup", () => {
  it("is not visible when clipId is null", async () => {
    mountDialog(null);
    await nextTick();
    expect(document.body.querySelector('[data-testid="report-missed-face-dialog"]')).toBeFalsy();
  });

  it("loads people and the frame picker once opened", async () => {
    await mountOpen();
    expect(mockedListPeople).toHaveBeenCalledTimes(1);
    expect(mockedDetectFaces).toHaveBeenCalledWith("clip-1", 5);
  });

  it("shows the people load error message", async () => {
    mockedListPeople.mockRejectedValue(new ApiError(500, "Server exploded"));
    await mountOpen();
    expect(document.body.textContent).toContain("Server exploded");
  });

  it("falls back to a generic people load error for non-API failures", async () => {
    mockedListPeople.mockRejectedValue(new TypeError("down"));
    await mountOpen();
    expect(document.body.textContent).toContain("Could not load people.");
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

  it("does not re-fetch people for a second clip, but does reset the session", async () => {
    const wrapper = await mountOpen("clip-1");
    await wrapper.setProps({ clipId: "clip-2" });
    await flushPromises();
    expect(mockedListPeople).toHaveBeenCalledTimes(1);
  });

  it("does nothing when clipId is set to null (dialog closing)", async () => {
    const wrapper = await mountOpen("clip-1");
    await wrapper.setProps({ clipId: null });
    await flushPromises();
    expect(mockedListPeople).toHaveBeenCalledTimes(1);
  });
});

describe("ReportMissedFaceDialog who-picker", () => {
  it("disables Enroll until a face and a person are both chosen", async () => {
    await mountOpen();
    const confirmButton = document.body.querySelector<HTMLButtonElement>(
      '[data-testid="report-missed-face-confirm"]',
    );
    expect(confirmButton?.disabled).toBe(true);
  });

  it("clears the new-name field when an existing person is selected", async () => {
    const wrapper = await mountOpen();
    await pickAFace();
    const input = document.body.querySelector<HTMLInputElement>(
      '[data-testid="report-missed-new-person-name"]',
    )!;
    input.value = "Someone New";
    input.dispatchEvent(new Event("input"));
    await nextTick();

    await wrapper.findComponent({ name: "Select" }).vm.$emit("update:modelValue", "p-1");
    await nextTick();

    expect(input.value).toBe("");
  });

  it("clears the selected person when a new name is typed", async () => {
    const wrapper = await mountOpen();
    await pickAFace();
    await wrapper.findComponent({ name: "Select" }).vm.$emit("update:modelValue", "p-1");
    await nextTick();

    const input = document.body.querySelector<HTMLInputElement>(
      '[data-testid="report-missed-new-person-name"]',
    )!;
    input.value = "Someone New";
    input.dispatchEvent(new Event("input"));
    await nextTick();

    expect(wrapper.findComponent({ name: "Select" }).props("modelValue")).toBeNull();
  });

  it("enables Enroll once a face and an existing person are chosen", async () => {
    const wrapper = await mountOpen();
    await pickAFace();
    await wrapper.findComponent({ name: "Select" }).vm.$emit("update:modelValue", "p-1");
    await nextTick();
    const confirmButton = document.body.querySelector<HTMLButtonElement>(
      '[data-testid="report-missed-face-confirm"]',
    );
    expect(confirmButton?.disabled).toBe(false);
  });

  it("enables Enroll once a face and a new person name are chosen", async () => {
    await mountOpen();
    await pickAFace();
    const input = document.body.querySelector<HTMLInputElement>(
      '[data-testid="report-missed-new-person-name"]',
    )!;
    input.value = "Jordan";
    input.dispatchEvent(new Event("input"));
    await nextTick();
    const confirmButton = document.body.querySelector<HTMLButtonElement>(
      '[data-testid="report-missed-face-confirm"]',
    );
    expect(confirmButton?.disabled).toBe(false);
  });
});

describe("ReportMissedFaceDialog submit", () => {
  it("enrolls directly against an existing selected person", async () => {
    mockedEnrollFace.mockResolvedValue({
      id: "face-1",
      source_clip_id: "clip-1",
      source_frame_seconds: 5,
      created_at: "2026-07-20T00:00:00Z",
    });
    const wrapper = await mountOpen();
    await pickAFace();
    await wrapper.findComponent({ name: "Select" }).vm.$emit("update:modelValue", "p-1");
    await nextTick();

    document.body.querySelector<HTMLElement>('[data-testid="report-missed-face-confirm"]')?.click();
    await flushPromises();

    expect(mockedCreatePerson).not.toHaveBeenCalled();
    expect(mockedEnrollFace).toHaveBeenCalledWith("p-1", {
      clip_id: "clip-1",
      frame_seconds: 5,
      bbox: [0.1, 0.1, 0.2, 0.2],
    });
    expect(wrapper.emitted("enrolled")).toHaveLength(1);
    expect(wrapper.emitted("close")).toHaveLength(1);
  });

  it("creates a new person first, then enrolls against them", async () => {
    mockedCreatePerson.mockResolvedValue(makePerson({ id: "p-new", name: "Jordan" }));
    mockedEnrollFace.mockResolvedValue({
      id: "face-1",
      source_clip_id: "clip-1",
      source_frame_seconds: 5,
      created_at: "2026-07-20T00:00:00Z",
    });
    await mountOpen();
    await pickAFace();
    const input = document.body.querySelector<HTMLInputElement>(
      '[data-testid="report-missed-new-person-name"]',
    )!;
    input.value = "  Jordan  ";
    input.dispatchEvent(new Event("input"));
    await nextTick();

    document.body.querySelector<HTMLElement>('[data-testid="report-missed-face-confirm"]')?.click();
    await flushPromises();

    expect(mockedCreatePerson).toHaveBeenCalledWith({ name: "Jordan" });
    expect(mockedEnrollFace).toHaveBeenCalledWith("p-new", {
      clip_id: "clip-1",
      frame_seconds: 5,
      bbox: [0.1, 0.1, 0.2, 0.2],
    });
  });

  it("shows the API error message when enrollment fails and stays open", async () => {
    mockedEnrollFace.mockRejectedValue(new ApiError(404, "No detected face matches that selection."));
    const wrapper = await mountOpen();
    await pickAFace();
    await wrapper.findComponent({ name: "Select" }).vm.$emit("update:modelValue", "p-1");
    await nextTick();

    document.body.querySelector<HTMLElement>('[data-testid="report-missed-face-confirm"]')?.click();
    await flushPromises();

    expect(document.body.textContent).toContain("No detected face matches that selection.");
    expect(wrapper.emitted("enrolled")).toBeUndefined();
  });

  it("falls back to a generic error for a non-API enrollment failure", async () => {
    mockedEnrollFace.mockRejectedValue(new TypeError("down"));
    const wrapper = await mountOpen();
    await pickAFace();
    await wrapper.findComponent({ name: "Select" }).vm.$emit("update:modelValue", "p-1");
    await nextTick();

    document.body.querySelector<HTMLElement>('[data-testid="report-missed-face-confirm"]')?.click();
    await flushPromises();
    expect(document.body.textContent).toContain("Could not enroll this face.");
  });

  it("closes via the Cancel button", async () => {
    const wrapper = await mountOpen();
    const buttons = [...document.body.querySelectorAll("button")];
    const cancel = buttons.find((b) => b.textContent?.trim() === "Cancel");
    cancel?.click();
    await flushPromises();
    expect(wrapper.emitted("close")).toHaveLength(1);
  });
});
