import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";

vi.mock("video.js", () => ({
  default: vi.fn(() => ({ dispose: vi.fn(), src: vi.fn() })),
}));
vi.mock("video.js/dist/video-js.css", () => ({}));

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  getClipAnalysis: vi.fn(),
  reanalyzeClip: vi.fn(),
  submitFeedback: vi.fn(),
  reportFalsePositive: vi.fn(),
  listPeople: vi.fn(),
  createPerson: vi.fn(),
  detectFacesInClipFrame: vi.fn(),
  enrollFace: vi.fn(),
}));

const toastAdd = vi.fn();
vi.mock("primevue/usetoast", () => ({ useToast: () => ({ add: toastAdd }) }));

const confirmRequire = vi.fn();
vi.mock("primevue/useconfirm", () => ({ useConfirm: () => ({ require: confirmRequire }) }));

import {
  detectFacesInClipFrame,
  getClipAnalysis,
  listPeople,
  reanalyzeClip,
  reportFalsePositive,
  submitFeedback,
} from "@/api";
import { ApiError } from "@/api/client";
import ClipDetailModal from "@/components/ClipDetailModal.vue";
import VideoPlayer from "@/components/VideoPlayer.vue";
import { makePinia, mountGlobal } from "./helpers";

import type { AnalysisRead, ClipRead } from "@/api";

const mockedGetAnalysis = vi.mocked(getClipAnalysis);
const mockedReanalyze = vi.mocked(reanalyzeClip);
const mockedSubmitFeedback = vi.mocked(submitFeedback);
const mockedReportFalsePositive = vi.mocked(reportFalsePositive);
const mockedListPeople = vi.mocked(listPeople);
const mockedDetectFaces = vi.mocked(detectFacesInClipFrame);

const clip: ClipRead = {
  id: "clip-1",
  camera_id: "cam-1",
  recorded_at: "2026-07-20T18:30:00Z",
  duration_seconds: 65,
  file_size_bytes: 2048,
  downloaded_at: "2026-07-20T18:31:00Z",
  deleted_on_blink: false,
  thumbnail_generated: true,
  storage_backend: "local",
  recognized_people: [],
};

const otherClip: ClipRead = { ...clip, id: "clip-2" };

const routineAnalysis: AnalysisRead = {
  id: "an-1",
  clip_id: "clip-1",
  summary: "A person walks to the front door and leaves a package.",
  suspicion_score: 0.12,
  suspicion_label: "routine",
  tier: "tier1",
  escalated: false,
  tier1_provider: "openai",
  tier1_model: "gpt-4o-mini",
  tier2_provider: null,
  tier2_model: null,
  detected_entities: [
    { type: "person", label: "person", confidence: 0.95, bbox: [0.1, 0.1, 0.2, 0.4] },
  ],
  vehicle_proximity: null,
  created_at: "2026-07-20T18:32:00Z",
};

const suspiciousAnalysis: AnalysisRead = {
  ...routineAnalysis,
  suspicion_score: 0.81,
  suspicion_label: "suspicious",
  tier: "tier2",
  escalated: true,
  tier2_provider: "anthropic",
  tier2_model: "claude-haiku-4-5",
  vehicle_proximity: {
    vehicle_id: "veh-1",
    distance_feet: 3.4,
    error_margin_feet: 1.2,
    breached_threshold: true,
  },
};

function notFound(): ApiError {
  return new ApiError(404, "This clip has not been analyzed yet.");
}

// PrimeVue's Dialog teleports its content to document.body one tick after
// mount (an overlay-positioning step); analysis is then fetched
// asynchronously. Query the real document after nextTick + flushPromises
// rather than stubbing Teleport (which renders an empty placeholder).
async function mountModal(clipProp: ClipRead | null, canManage = true) {
  const wrapper = mount(ClipDetailModal, {
    props: { clip: clipProp, cameraName: "Front Door", canManage },
    global: mountGlobal(makePinia()),
    attachTo: document.body,
  });
  await nextTick();
  await flushPromises();
  return wrapper;
}

beforeEach(() => {
  vi.clearAllMocks();
  mockedListPeople.mockResolvedValue([]);
  mockedDetectFaces.mockResolvedValue([]);
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("ClipDetailModal — base rendering", () => {
  it("is not visible when clip is null", async () => {
    const wrapper = await mountModal(null);
    expect(wrapper.findComponent({ name: "Dialog" }).props("visible")).toBe(false);
  });

  it("shows the player and metadata for a downloaded clip", async () => {
    mockedGetAnalysis.mockRejectedValue(notFound());
    const wrapper = await mountModal(clip);
    expect(wrapper.findComponent(VideoPlayer).exists()).toBe(true);
    expect(wrapper.findComponent(VideoPlayer).props("src")).toBe("/api/clips/clip-1/stream");
    expect(wrapper.findComponent(VideoPlayer).props("poster")).toBe("/api/clips/clip-1/thumbnail");
    expect(document.body.textContent).toContain("1:05");
    expect(document.body.textContent).toContain("2.0 KB");
  });

  it("lets the dialog be maximized so the player gets full-viewport room", async () => {
    mockedGetAnalysis.mockRejectedValue(notFound());
    const wrapper = await mountModal(clip);
    expect(wrapper.findComponent({ name: "Dialog" }).props("maximizable")).toBe(true);
  });

  it("keeps the video and primary actions in the main column, metadata and AI in the sidebar", async () => {
    mockedGetAnalysis.mockRejectedValue(notFound());
    await mountModal(clip);
    const main = document.body.querySelector(".modal-main");
    const sidebar = document.body.querySelector(".modal-sidebar");
    expect(main?.querySelector('[data-testid="modal-download"]')).toBeTruthy();
    expect(sidebar?.querySelector(".meta-grid")).toBeTruthy();
    expect(sidebar?.querySelector(".ai-section")).toBeTruthy();
    expect(main?.querySelector(".ai-section")).toBeNull();
  });

  it("omits the poster when no thumbnail has been generated", async () => {
    mockedGetAnalysis.mockRejectedValue(notFound());
    const wrapper = await mountModal({ ...clip, thumbnail_generated: false });
    expect(wrapper.findComponent(VideoPlayer).props("poster")).toBeUndefined();
  });

  it("shows a not-ready message instead of the player when undownloaded", async () => {
    mockedGetAnalysis.mockRejectedValue(notFound());
    const wrapper = await mountModal({ ...clip, downloaded_at: null });
    expect(wrapper.findComponent(VideoPlayer).exists()).toBe(false);
    expect(document.body.textContent).toContain("hasn't finished downloading");
  });

  it("renders a download link for a downloaded clip", async () => {
    mockedGetAnalysis.mockRejectedValue(notFound());
    await mountModal(clip);
    const link = document.body.querySelector('[data-testid="modal-download"]');
    expect(link?.getAttribute("href")).toBe("/api/clips/clip-1/download");
  });

  it("omits the download link when the clip isn't downloaded", async () => {
    mockedGetAnalysis.mockRejectedValue(notFound());
    await mountModal({ ...clip, downloaded_at: null });
    expect(document.body.querySelector('[data-testid="modal-download"]')).toBeNull();
  });

  it("emits delete when the delete button is clicked", async () => {
    mockedGetAnalysis.mockRejectedValue(notFound());
    const wrapper = await mountModal(clip);
    const button = document.body.querySelector<HTMLElement>('[data-testid="modal-delete"]');
    button?.click();
    await nextTick();
    expect(wrapper.emitted("delete")).toHaveLength(1);
  });

  it("hides download and delete for a viewer account (canManage false)", async () => {
    mockedGetAnalysis.mockRejectedValue(notFound());
    await mountModal(clip, false);
    expect(document.body.querySelector('[data-testid="modal-download"]')).toBeNull();
    expect(document.body.querySelector('[data-testid="modal-delete"]')).toBeNull();
  });

  it("emits close when the dialog's visible model turns false", async () => {
    mockedGetAnalysis.mockRejectedValue(notFound());
    const wrapper = await mountModal(clip);
    await wrapper.findComponent({ name: "Dialog" }).vm.$emit("update:visible", false);
    expect(wrapper.emitted("close")).toHaveLength(1);
  });

  it("does not emit close when the dialog's visible model turns true", async () => {
    mockedGetAnalysis.mockRejectedValue(notFound());
    const wrapper = await mountModal(clip);
    await wrapper.findComponent({ name: "Dialog" }).vm.$emit("update:visible", true);
    expect(wrapper.emitted("close")).toBeUndefined();
  });
});

describe("ClipDetailModal — AI analysis loading", () => {
  it("shows a loading skeleton while fetching", async () => {
    mockedGetAnalysis.mockReturnValue(new Promise(() => {}));
    mount(ClipDetailModal, {
      props: { clip, cameraName: "Front Door" },
      global: mountGlobal(makePinia()),
      attachTo: document.body,
    });
    await nextTick();
    expect(document.body.querySelector('[data-testid="analysis-loading"]')).toBeTruthy();
  });

  it("shows a not-yet-analyzed message on a 404", async () => {
    mockedGetAnalysis.mockRejectedValue(notFound());
    await mountModal(clip);
    expect(document.body.textContent).toContain("hasn't been analyzed yet");
  });

  it("shows the API error message for a non-404 failure", async () => {
    mockedGetAnalysis.mockRejectedValue(new ApiError(500, "Server exploded"));
    await mountModal(clip);
    expect(
      document.body.querySelector('[data-testid="analysis-error"]')?.textContent,
    ).toContain("Server exploded");
  });

  it("falls back to a generic error message for non-API failures", async () => {
    mockedGetAnalysis.mockRejectedValue(new TypeError("down"));
    await mountModal(clip);
    expect(
      document.body.querySelector('[data-testid="analysis-error"]')?.textContent,
    ).toContain("Could not load AI analysis.");
  });

  it("re-fetches when the clip prop changes to a different clip", async () => {
    mockedGetAnalysis.mockResolvedValueOnce(routineAnalysis).mockRejectedValueOnce(notFound());
    const wrapper = await mountModal(clip);
    expect(mockedGetAnalysis).toHaveBeenCalledWith("clip-1");
    expect(document.body.textContent).toContain("A person walks to the front door");

    await wrapper.setProps({ clip: otherClip });
    await nextTick();
    await flushPromises();
    expect(mockedGetAnalysis).toHaveBeenCalledWith("clip-2");
    expect(document.body.textContent).toContain("hasn't been analyzed yet");
  });
});

describe("ClipDetailModal — analyzed content", () => {
  it("renders the label, score, summary, and detected entities", async () => {
    mockedGetAnalysis.mockResolvedValue(routineAnalysis);
    await mountModal(clip);
    const body = document.body.querySelector('[data-testid="analysis-body"]');
    expect(body?.textContent).toContain("routine");
    expect(body?.textContent).toContain("12% suspicion");
    expect(body?.textContent).toContain("A person walks to the front door and leaves a package.");
    expect(body?.textContent).toContain("person (95%)");
    expect(document.body.querySelector('[data-testid="proximity-note"]')).toBeNull();
  });

  it("shows an escalated tag and vehicle proximity note when present", async () => {
    mockedGetAnalysis.mockResolvedValue(suspiciousAnalysis);
    await mountModal(clip);
    expect(document.body.textContent).toContain("Escalated to Tier 2");
    const note = document.body.querySelector('[data-testid="proximity-note"]');
    expect(note?.textContent).toContain("3.4 ft");
    expect(note?.textContent).toContain("±1.2 ft");
    expect(note?.className).toContain("breach");
  });

  it("omits entity tags when nothing was detected", async () => {
    mockedGetAnalysis.mockResolvedValue({ ...routineAnalysis, detected_entities: [] });
    await mountModal(clip);
    expect(document.body.querySelector(".entities")).toBeNull();
  });

  it("shows a distinct recognized treatment for a locally-upgraded entity label", async () => {
    mockedGetAnalysis.mockResolvedValue({
      ...routineAnalysis,
      detected_entities: [
        {
          type: "person",
          label: "Alex",
          confidence: 0.95,
          bbox: [0.1, 0.1, 0.2, 0.4],
          recognized_person_id: "person-1",
        },
      ],
    });
    await mountModal(clip);
    const tag = document.body.querySelector('[data-testid="recognized-entity-tag"]');
    expect(tag?.textContent).toContain("Alex (95%)");
    expect(tag?.className).toContain("recognized");
  });

  it("leaves an unrecognized entity's tag in the plain style", async () => {
    mockedGetAnalysis.mockResolvedValue(routineAnalysis);
    await mountModal(clip);
    expect(document.body.querySelector('[data-testid="recognized-entity-tag"]')).toBeNull();
    const tag = document.body.querySelector(".entity-tag");
    expect(tag?.className).not.toContain("recognized");
  });
});

describe("ClipDetailModal — re-analyze", () => {
  it("shows Analyze now before any analysis exists, for an admin", async () => {
    mockedGetAnalysis.mockRejectedValue(notFound());
    await mountModal(clip);
    const button = document.body.querySelector('[data-testid="reanalyze"]');
    expect(button?.textContent).toContain("Analyze now");
  });

  it("shows Re-analyze once an analysis exists", async () => {
    mockedGetAnalysis.mockResolvedValue(routineAnalysis);
    await mountModal(clip);
    expect(document.body.querySelector('[data-testid="reanalyze"]')?.textContent).toContain(
      "Re-analyze",
    );
  });

  it("is hidden for a viewer account", async () => {
    mockedGetAnalysis.mockResolvedValue(routineAnalysis);
    await mountModal(clip, false);
    expect(document.body.querySelector('[data-testid="reanalyze"]')).toBeNull();
  });

  it("is hidden when the clip hasn't downloaded yet", async () => {
    mockedGetAnalysis.mockRejectedValue(notFound());
    await mountModal({ ...clip, downloaded_at: null });
    expect(document.body.querySelector('[data-testid="reanalyze"]')).toBeNull();
  });

  it("queues analysis and toasts success", async () => {
    mockedGetAnalysis.mockResolvedValue(routineAnalysis);
    mockedReanalyze.mockResolvedValue({ status: "queued" });
    await mountModal(clip);
    document.body.querySelector<HTMLElement>('[data-testid="reanalyze"]')?.click();
    await flushPromises();
    expect(mockedReanalyze).toHaveBeenCalledWith("clip-1");
    expect(toastAdd).toHaveBeenCalledWith(expect.objectContaining({ severity: "success" }));
  });

  it("toasts the API error message when queuing fails", async () => {
    mockedGetAnalysis.mockResolvedValue(routineAnalysis);
    mockedReanalyze.mockRejectedValue(new ApiError(400, "This clip has not been downloaded yet."));
    await mountModal(clip);
    document.body.querySelector<HTMLElement>('[data-testid="reanalyze"]')?.click();
    await flushPromises();
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({
        severity: "error",
        detail: "This clip has not been downloaded yet.",
      }),
    );
  });

  it("toasts a generic error for a non-API failure", async () => {
    mockedGetAnalysis.mockResolvedValue(routineAnalysis);
    mockedReanalyze.mockRejectedValue(new TypeError("down"));
    await mountModal(clip);
    document.body.querySelector<HTMLElement>('[data-testid="reanalyze"]')?.click();
    await flushPromises();
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "error", detail: "Unexpected error." }),
    );
  });
});

describe("ClipDetailModal — feedback", () => {
  it("offers 'Actually suspicious' for a routine analysis", async () => {
    mockedGetAnalysis.mockResolvedValue(routineAnalysis);
    await mountModal(clip);
    expect(document.body.querySelector('[data-testid="feedback-false-negative"]')).toBeTruthy();
    expect(document.body.querySelector('[data-testid="feedback-false-positive"]')).toBeNull();
  });

  it("offers 'Not suspicious' for a suspicious/uncertain analysis", async () => {
    mockedGetAnalysis.mockResolvedValue(suspiciousAnalysis);
    await mountModal(clip);
    expect(document.body.querySelector('[data-testid="feedback-false-positive"]')).toBeTruthy();
    expect(document.body.querySelector('[data-testid="feedback-false-negative"]')).toBeNull();
  });

  it("submits 'correct' feedback and shows a thank-you in place of the buttons", async () => {
    mockedGetAnalysis.mockResolvedValue(routineAnalysis);
    mockedSubmitFeedback.mockResolvedValue({
      id: "fb-1",
      analysis_id: "an-1",
      user_id: "u-1",
      verdict: "correct",
      note: null,
      applied: true,
      created_at: "2026-07-20T18:33:00Z",
    });
    await mountModal(clip);
    document.body.querySelector<HTMLElement>('[data-testid="feedback-correct"]')?.click();
    await flushPromises();
    expect(mockedSubmitFeedback).toHaveBeenCalledWith("clip-1", {
      verdict: "correct",
      note: null,
    });
    expect(document.body.querySelector('[data-testid="feedback-thanks"]')).toBeTruthy();
    expect(document.body.querySelector('[data-testid="feedback-correct"]')).toBeNull();
  });

  it("submits false_negative feedback for a routine analysis", async () => {
    mockedGetAnalysis.mockResolvedValue(routineAnalysis);
    mockedSubmitFeedback.mockResolvedValue({
      id: "fb-1",
      analysis_id: "an-1",
      user_id: "u-1",
      verdict: "false_negative",
      note: null,
      applied: true,
      created_at: "2026-07-20T18:33:00Z",
    });
    await mountModal(clip);
    document.body
      .querySelector<HTMLElement>('[data-testid="feedback-false-negative"]')
      ?.click();
    await flushPromises();
    expect(mockedSubmitFeedback).toHaveBeenCalledWith("clip-1", {
      verdict: "false_negative",
      note: null,
    });
  });

  it("submits false_positive feedback for a suspicious analysis", async () => {
    mockedGetAnalysis.mockResolvedValue(suspiciousAnalysis);
    mockedSubmitFeedback.mockResolvedValue({
      id: "fb-1",
      analysis_id: "an-1",
      user_id: "u-1",
      verdict: "false_positive",
      note: null,
      applied: true,
      created_at: "2026-07-20T18:33:00Z",
    });
    await mountModal(clip);
    document.body
      .querySelector<HTMLElement>('[data-testid="feedback-false-positive"]')
      ?.click();
    await flushPromises();
    expect(mockedSubmitFeedback).toHaveBeenCalledWith("clip-1", {
      verdict: "false_positive",
      note: null,
    });
  });

  it("toasts the API error message when feedback submission fails", async () => {
    mockedGetAnalysis.mockResolvedValue(routineAnalysis);
    mockedSubmitFeedback.mockRejectedValue(new ApiError(404, "This clip has not been analyzed yet."));
    await mountModal(clip);
    document.body.querySelector<HTMLElement>('[data-testid="feedback-correct"]')?.click();
    await flushPromises();
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({
        severity: "error",
        detail: "This clip has not been analyzed yet.",
      }),
    );
    expect(document.body.querySelector('[data-testid="feedback-thanks"]')).toBeNull();
  });

  it("toasts a generic error for a non-API feedback failure", async () => {
    mockedGetAnalysis.mockResolvedValue(routineAnalysis);
    mockedSubmitFeedback.mockRejectedValue(new TypeError("down"));
    await mountModal(clip);
    document.body.querySelector<HTMLElement>('[data-testid="feedback-correct"]')?.click();
    await flushPromises();
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "error", detail: "Unexpected error." }),
    );
  });

  it("resets the feedback-given state when a different clip is opened", async () => {
    mockedGetAnalysis.mockResolvedValue(routineAnalysis);
    mockedSubmitFeedback.mockResolvedValue({
      id: "fb-1",
      analysis_id: "an-1",
      user_id: "u-1",
      verdict: "correct",
      note: null,
      applied: true,
      created_at: "2026-07-20T18:33:00Z",
    });
    const wrapper = await mountModal(clip);
    document.body.querySelector<HTMLElement>('[data-testid="feedback-correct"]')?.click();
    await flushPromises();
    expect(document.body.querySelector('[data-testid="feedback-thanks"]')).toBeTruthy();

    mockedGetAnalysis.mockResolvedValue(suspiciousAnalysis);
    await wrapper.setProps({ clip: otherClip });
    await nextTick();
    await flushPromises();
    expect(document.body.querySelector('[data-testid="feedback-thanks"]')).toBeNull();
  });
});

const recognizedAnalysis: AnalysisRead = {
  ...routineAnalysis,
  detected_entities: [
    {
      type: "person",
      label: "Alex",
      confidence: 0.95,
      bbox: [0.1, 0.1, 0.2, 0.4],
      recognized_person_id: "person-1",
    },
  ],
};

describe("ClipDetailModal — report a false positive", () => {
  it("shows a report action only on recognized entities, and only for an admin", async () => {
    mockedGetAnalysis.mockResolvedValue(recognizedAnalysis);
    await mountModal(clip);
    expect(
      document.body.querySelector('[data-testid="report-false-positive-person-1"]'),
    ).toBeTruthy();
  });

  it("hides the report action for a viewer account", async () => {
    mockedGetAnalysis.mockResolvedValue(recognizedAnalysis);
    await mountModal(clip, false);
    expect(
      document.body.querySelector('[data-testid="report-false-positive-person-1"]'),
    ).toBeNull();
  });

  it("omits the report action for an unrecognized entity", async () => {
    mockedGetAnalysis.mockResolvedValue(routineAnalysis);
    await mountModal(clip);
    expect(document.body.querySelector(".report-mismatch")).toBeNull();
  });

  it("asks for confirmation naming the recognized person before reporting", async () => {
    mockedGetAnalysis.mockResolvedValue(recognizedAnalysis);
    await mountModal(clip);
    document.body
      .querySelector<HTMLElement>('[data-testid="report-false-positive-person-1"]')
      ?.click();
    await nextTick();
    const options = confirmRequire.mock.calls.at(-1)?.[0] as { message: string };
    expect(options.message).toContain("Alex");
  });

  it("reports the false positive on confirm, toasts, and reloads the analysis", async () => {
    mockedGetAnalysis.mockResolvedValueOnce(recognizedAnalysis).mockResolvedValueOnce(routineAnalysis);
    mockedReportFalsePositive.mockResolvedValue({ negative_sample_captured: true });
    await mountModal(clip);

    document.body
      .querySelector<HTMLElement>('[data-testid="report-false-positive-person-1"]')
      ?.click();
    await nextTick();
    const options = confirmRequire.mock.calls.at(-1)?.[0] as { accept: () => void };
    options.accept();
    await flushPromises();

    expect(mockedReportFalsePositive).toHaveBeenCalledWith("clip-1", "person-1");
    expect(toastAdd).toHaveBeenCalledWith(expect.objectContaining({ severity: "success" }));
    expect(mockedGetAnalysis).toHaveBeenCalledTimes(2);
  });

  it("toasts the API error message when reporting fails", async () => {
    mockedGetAnalysis.mockResolvedValue(recognizedAnalysis);
    mockedReportFalsePositive.mockRejectedValue(new ApiError(502, "Could not download the model."));
    await mountModal(clip);

    document.body
      .querySelector<HTMLElement>('[data-testid="report-false-positive-person-1"]')
      ?.click();
    await nextTick();
    const options = confirmRequire.mock.calls.at(-1)?.[0] as { accept: () => void };
    options.accept();
    await flushPromises();

    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "error", detail: "Could not download the model." }),
    );
  });

  it("toasts a generic error for a non-API reporting failure", async () => {
    mockedGetAnalysis.mockResolvedValue(recognizedAnalysis);
    mockedReportFalsePositive.mockRejectedValue(new TypeError("down"));
    await mountModal(clip);

    document.body
      .querySelector<HTMLElement>('[data-testid="report-false-positive-person-1"]')
      ?.click();
    await nextTick();
    const options = confirmRequire.mock.calls.at(-1)?.[0] as { accept: () => void };
    options.accept();
    await flushPromises();

    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "error", detail: "Unexpected error." }),
    );
  });
});

describe("ClipDetailModal — report a missed face", () => {
  it("is shown for a viewer account too (enrollment isn't admin-only)", async () => {
    mockedGetAnalysis.mockResolvedValue(routineAnalysis);
    await mountModal(clip, false);
    expect(document.body.querySelector('[data-testid="report-missed-face"]')).toBeTruthy();
  });

  it("is hidden when the clip hasn't downloaded yet", async () => {
    mockedGetAnalysis.mockRejectedValue(notFound());
    await mountModal({ ...clip, downloaded_at: null });
    expect(document.body.querySelector('[data-testid="report-missed-face"]')).toBeNull();
  });

  it("opens the missed-face dialog scoped to the current clip", async () => {
    mockedGetAnalysis.mockResolvedValue(routineAnalysis);
    const wrapper = await mountModal(clip);

    document.body.querySelector<HTMLElement>('[data-testid="report-missed-face"]')?.click();
    await flushPromises();

    expect(
      wrapper.findComponent({ name: "ReportMissedFaceDialog" }).props("clipId"),
    ).toBe("clip-1");
    expect(document.body.querySelector('[data-testid="report-missed-face-dialog"]')).toBeTruthy();
  });

  it("closes the missed-face dialog on its close event", async () => {
    mockedGetAnalysis.mockResolvedValue(routineAnalysis);
    const wrapper = await mountModal(clip);
    document.body.querySelector<HTMLElement>('[data-testid="report-missed-face"]')?.click();
    await flushPromises();

    await wrapper.findComponent({ name: "ReportMissedFaceDialog" }).vm.$emit("close");
    await flushPromises();
    expect(
      wrapper.findComponent({ name: "ReportMissedFaceDialog" }).props("clipId"),
    ).toBeNull();
  });

  it("toasts and reloads the analysis when a missed face is enrolled", async () => {
    mockedGetAnalysis.mockResolvedValue(routineAnalysis);
    const wrapper = await mountModal(clip);
    document.body.querySelector<HTMLElement>('[data-testid="report-missed-face"]')?.click();
    await flushPromises();
    mockedGetAnalysis.mockClear();

    await wrapper.findComponent({ name: "ReportMissedFaceDialog" }).vm.$emit("enrolled");
    await flushPromises();

    expect(toastAdd).toHaveBeenCalledWith(expect.objectContaining({ severity: "success" }));
    expect(mockedGetAnalysis).toHaveBeenCalledWith("clip-1");
  });

  it("skips reloading the analysis if the clip closed before the missed face finished enrolling", async () => {
    mockedGetAnalysis.mockResolvedValue(routineAnalysis);
    const wrapper = await mountModal(clip);
    document.body.querySelector<HTMLElement>('[data-testid="report-missed-face"]')?.click();
    await flushPromises();

    await wrapper.setProps({ clip: null });
    mockedGetAnalysis.mockClear();
    await wrapper.findComponent({ name: "ReportMissedFaceDialog" }).vm.$emit("enrolled");
    await flushPromises();

    expect(toastAdd).toHaveBeenCalledWith(expect.objectContaining({ severity: "success" }));
    expect(mockedGetAnalysis).not.toHaveBeenCalled();
  });
});
