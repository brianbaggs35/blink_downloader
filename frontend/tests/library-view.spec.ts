import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

// LibraryView can open ClipDetailModal, which renders a real VideoPlayer -
// same mock as video-player.spec.ts/clip-detail-modal.spec.ts, otherwise an
// unmocked video.js tries to actually load the fake clip src (happy-dom
// resolves the relative URL against its default http://localhost:3000
// origin) and logs a real ECONNREFUSED plus a MEDIA_ERR_SRC_NOT_SUPPORTED.
vi.mock("video.js", () => ({
  default: vi.fn(() => ({ dispose: vi.fn(), src: vi.fn() })),
}));
vi.mock("video.js/dist/video-js.css", () => ({}));

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  getBlinkStatus: vi.fn(),
  listCameras: vi.fn(),
  listClips: vi.fn(),
  listPeople: vi.fn(),
  deleteClip: vi.fn(),
  bulkDeleteClips: vi.fn(),
  bulkAnalyzeClips: vi.fn(),
  downloadClipsAsZip: vi.fn(),
  getStorageIntegrationSettings: vi.fn(),
  archiveClips: vi.fn(),
  restoreClips: vi.fn(),
}));

const toastAdd = vi.fn();
vi.mock("primevue/usetoast", () => ({ useToast: () => ({ add: toastAdd }) }));

const confirmRequire = vi.fn();
vi.mock("primevue/useconfirm", () => ({ useConfirm: () => ({ require: confirmRequire }) }));

import {
  archiveClips,
  bulkAnalyzeClips,
  bulkDeleteClips,
  deleteClip,
  downloadClipsAsZip,
  getBlinkStatus,
  getStorageIntegrationSettings,
  listCameras,
  listClips,
  listPeople,
  restoreClips,
} from "@/api";
import { ApiError } from "@/api/client";
import ClipCard from "@/components/ClipCard.vue";
import ClipDetailModal from "@/components/ClipDetailModal.vue";
import ToggleButton from "primevue/togglebutton";
import { useAuthStore } from "@/stores/auth";
import LibraryView from "@/views/LibraryView.vue";
import { fakeStorageIntegrationSettings, fakeUser, makePinia, makeRouter, mountGlobal } from "./helpers";

import type { BlinkStatusResponse, CameraRead, ClipListParams, ClipListResponse, ClipRead } from "@/api";

const mockedStatus = vi.mocked(getBlinkStatus);
const mockedCameras = vi.mocked(listCameras);
const mockedClips = vi.mocked(listClips);
const mockedPeople = vi.mocked(listPeople);
const mockedDeleteClip = vi.mocked(deleteClip);
const mockedBulkDelete = vi.mocked(bulkDeleteClips);
const mockedBulkAnalyze = vi.mocked(bulkAnalyzeClips);
const mockedDownloadZip = vi.mocked(downloadClipsAsZip);
const mockedIntegrationSettings = vi.mocked(getStorageIntegrationSettings);
const mockedArchiveClips = vi.mocked(archiveClips);
const mockedRestoreClips = vi.mocked(restoreClips);

function linkedStatus(overrides: Partial<BlinkStatusResponse> = {}): BlinkStatusResponse {
  return {
    linked: true,
    status: "active",
    last_sync: null,
    last_error: null,
    camera_count: 2,
    network_ids: [],
    total_clip_count: 0,
    daily_clip_counts: [],
    ...overrides,
  };
}

function unlinkedStatus(): BlinkStatusResponse {
  return {
    linked: false,
    status: null,
    last_sync: null,
    last_error: null,
    camera_count: 0,
    network_ids: [],
    total_clip_count: 0,
    daily_clip_counts: [],
  };
}

const cameraA: CameraRead = {
  id: "cam-1",
  name: "Front Door",
  camera_type: "outdoor",
  enabled: true,
  battery: "ok",
  last_synced_at: null,
  security_context: null,
};

const cameraB: CameraRead = {
  id: "cam-2",
  name: "Backyard",
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
    recorded_at: "2026-07-20T18:30:00Z",
    duration_seconds: 30,
    file_size_bytes: 1024,
    downloaded_at: "2026-07-20T18:31:00Z",
    deleted_on_blink: false,
    thumbnail_generated: true,
    storage_backend: "local",
    recognized_people: [],
    ...overrides,
  };
}

function clipsResponse(items: ClipRead[], total = items.length, page = 1): ClipListResponse {
  return { items, total, page, page_size: 24 };
}

function makeClips(count: number, startIndex = 1): ClipRead[] {
  return Array.from({ length: count }, (_, i) => makeClip({ id: `clip-${startIndex + i}` }));
}

/** Routes listClips calls to a fixed response per page number, leaving the
 * separate recognized-count badge call (has_recognized_person: true) as an
 * empty/irrelevant response - used by the Prev/Next page-boundary tests,
 * which need to control exactly what each page number returns regardless of
 * call order. */
function pagedClipsMock(pages: Record<number, ClipListResponse>) {
  return async (params: ClipListParams = {}): Promise<ClipListResponse> => {
    if (params.has_recognized_person) {
      return clipsResponse([], 0);
    }
    const page = params.page ?? 1;
    // eslint-disable-next-line security/detect-object-injection
    return pages[page] ?? clipsResponse([], 0, page);
  };
}

async function mountLibrary(isAdmin = true) {
  const router = makeRouter();
  await router.push("/");
  const pinia = makePinia();
  useAuthStore().user = { ...fakeUser, is_superuser: isAdmin };
  const wrapper = mount(LibraryView, { global: mountGlobal(pinia, router) });
  await flushPromises();
  return { wrapper, router };
}

/** Two Select components can be on screen at once (the camera filter, and
 * the archive-destination picker) - find the right one by its data-testid,
 * since findComponent(selector) alone returns an untyped WrapperLike. */
function selectByTestId(wrapper: VueWrapper, testId: string) {
  const match = wrapper
    .findAllComponents({ name: "Select" })
    .find((s) => s.attributes("data-testid") === testId);
  if (!match) {
    throw new Error(`No Select found with data-testid="${testId}"`);
  }
  return match;
}

/** Grabs the options object passed to the most recent confirm.require() call
 * and invokes its accept callback, simulating the user confirming the dialog
 * (LibraryView never registers a reject callback, so there's nothing to
 * simulate on that path). */
function acceptLastConfirm(): void {
  const options = confirmRequire.mock.calls.at(-1)?.[0] as { accept: () => void };
  options.accept();
}

beforeEach(() => {
  vi.clearAllMocks();
  mockedCameras.mockResolvedValue([cameraA, cameraB]);
  mockedClips.mockResolvedValue(clipsResponse([]));
  mockedPeople.mockResolvedValue([]);
  mockedIntegrationSettings.mockResolvedValue(fakeStorageIntegrationSettings());
});

describe("LibraryView — unlinked", () => {
  it("shows the loading skeleton before status resolves", () => {
    mockedStatus.mockReturnValue(new Promise<BlinkStatusResponse>(() => {}));
    const wrapper = mount(LibraryView, { global: mountGlobal(makePinia(), makeRouter()) });
    expect(wrapper.find('[data-testid="loading"]').exists()).toBe(true);
  });

  it("offers a path to settings from the empty state", async () => {
    mockedStatus.mockResolvedValue(unlinkedStatus());
    const { wrapper, router } = await mountLibrary();

    expect(wrapper.find(".title").text()).toBe("Library");
    expect(wrapper.text()).toContain("Link your Blink account");
    expect(mockedClips).not.toHaveBeenCalled();

    await wrapper.find('[data-testid="go-settings"]').trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.name).toBe("settings");
  });
});

describe("LibraryView — status check failure", () => {
  it("shows a retry state instead of hanging when the status check fails", async () => {
    mockedStatus.mockRejectedValue(new TypeError("network down"));
    const { wrapper } = await mountLibrary();

    expect(wrapper.find('[data-testid="loading"]').exists()).toBe(false);
    expect(wrapper.text()).toContain("Couldn't check your Blink connection");
    expect(mockedCameras).not.toHaveBeenCalled();
    expect(mockedClips).not.toHaveBeenCalled();
  });

  it("retries and loads the library once the status check succeeds", async () => {
    mockedStatus
      .mockRejectedValueOnce(new TypeError("network down"))
      .mockResolvedValue(linkedStatus());
    mockedClips.mockResolvedValue(clipsResponse([makeClip()], 1));
    const { wrapper } = await mountLibrary();
    expect(wrapper.text()).toContain("Couldn't check your Blink connection");

    await wrapper.find('[data-testid="retry-status"]').trigger("click");
    await flushPromises();

    expect(wrapper.text()).not.toContain("Couldn't check your Blink connection");
    expect(wrapper.find('[data-testid="clip-grid"]').exists()).toBe(true);
  });
});

describe("LibraryView — linked, loading clips", () => {
  beforeEach(() => {
    mockedStatus.mockResolvedValue(linkedStatus());
  });

  it("loads cameras and clips and renders a card per clip with its camera name", async () => {
    const clipOne = makeClip({ id: "clip-1", camera_id: "cam-1" });
    const clipTwo = makeClip({ id: "clip-2", camera_id: "cam-2" });
    mockedClips.mockResolvedValue(clipsResponse([clipOne, clipTwo], 2));
    const { wrapper } = await mountLibrary();

    expect(wrapper.find('[data-testid="loading"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="clip-grid"]').exists()).toBe(true);
    const cards = wrapper.findAllComponents(ClipCard);
    expect(cards).toHaveLength(2);
    expect(cards[0]!.props("cameraName")).toBe("Front Door");
    expect(cards[1]!.props("cameraName")).toBe("Backyard");
  });

  it("falls back to 'Unknown camera' for a clip and an opened modal when the camera wasn't loaded", async () => {
    mockedClips.mockResolvedValue(clipsResponse([makeClip({ camera_id: "cam-missing" })], 1));
    const { wrapper } = await mountLibrary();

    expect(wrapper.findComponent(ClipCard).props("cameraName")).toBe("Unknown camera");

    await wrapper.findComponent(ClipCard).vm.$emit("open");
    await flushPromises();
    expect(wrapper.findComponent(ClipDetailModal).props("cameraName")).toBe("Unknown camera");
  });

  it("silently falls back to an empty camera list when loadCameras fails", async () => {
    mockedCameras.mockRejectedValue(new Error("network down"));
    mockedClips.mockResolvedValue(clipsResponse([makeClip()], 1));
    const { wrapper } = await mountLibrary();

    expect(wrapper.findComponent(ClipCard).props("cameraName")).toBe("Unknown camera");
    expect(toastAdd).not.toHaveBeenCalled();
  });

  it("silently falls back to an empty people list when loadPeople fails", async () => {
    mockedPeople.mockRejectedValue(new Error("network down"));
    mockedClips.mockResolvedValue(clipsResponse([makeClip()], 1));
    const { wrapper } = await mountLibrary();

    expect(wrapper.find('[data-testid="recognized-person-filter"]').exists()).toBe(false);
    expect(toastAdd).not.toHaveBeenCalled();
  });

  it("shows a no-clips empty state when there are no clips and no filters are active", async () => {
    mockedClips.mockResolvedValue(clipsResponse([]));
    const { wrapper } = await mountLibrary();

    expect(wrapper.text()).toContain("No clips yet");
    expect(wrapper.find('[data-testid="clear-filters"]').exists()).toBe(false);
  });

  it("shows an error toast with the API message when the initial clip load fails", async () => {
    mockedClips.mockRejectedValue(new ApiError(503, "Service unavailable."));
    const { wrapper } = await mountLibrary();

    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({
        severity: "error",
        summary: "Could not load clips",
        detail: "Service unavailable.",
      }),
    );
    expect(wrapper.find('[data-testid="loading"]').exists()).toBe(false);
  });

  it("shows a generic error detail when the initial clip load fails with a non-API error", async () => {
    mockedClips.mockRejectedValue(new TypeError("boom"));
    await mountLibrary();

    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ summary: "Could not load clips", detail: "Unexpected error." }),
    );
  });
});

describe("LibraryView — filters", () => {
  beforeEach(() => {
    mockedStatus.mockResolvedValue(linkedStatus());
  });

  it("reloads with the chosen camera, resets to page 1, and shows the clear-filters button", async () => {
    mockedClips
      .mockResolvedValueOnce(clipsResponse([makeClip()], 1))
      .mockResolvedValueOnce(clipsResponse([], 0));
    const { wrapper } = await mountLibrary();
    expect(wrapper.find('[data-testid="clear-filters"]').exists()).toBe(false);

    await wrapper.findComponent({ name: "Select" }).vm.$emit("update:modelValue", "cam-2");
    await flushPromises();

    expect(mockedClips).toHaveBeenLastCalledWith(
      expect.objectContaining({ camera_id: "cam-2", page: 1 }),
    );
    expect(wrapper.find('[data-testid="clear-filters"]').exists()).toBe(true);
    expect(wrapper.text()).toContain("No clips match these filters");
  });

  it("applies since/until date filters as ISO strings", async () => {
    mockedClips.mockResolvedValue(clipsResponse([makeClip()], 1));
    const { wrapper } = await mountLibrary();
    const datePickers = wrapper.findAllComponents({ name: "DatePicker" });

    const since = new Date("2026-07-01T00:00:00Z");
    await datePickers[0]!.vm.$emit("update:modelValue", since);
    await flushPromises();
    expect(mockedClips).toHaveBeenLastCalledWith(
      expect.objectContaining({ since: since.toISOString(), until: undefined }),
    );

    const until = new Date("2026-07-20T00:00:00Z");
    await datePickers[1]!.vm.$emit("update:modelValue", until);
    await flushPromises();
    expect(mockedClips).toHaveBeenLastCalledWith(
      expect.objectContaining({ since: since.toISOString(), until: until.toISOString() }),
    );
  });

  it("clears filters via the toolbar button and reloads with no filters", async () => {
    mockedClips.mockResolvedValue(clipsResponse([makeClip()], 1));
    const { wrapper } = await mountLibrary();

    await wrapper.findComponent({ name: "Select" }).vm.$emit("update:modelValue", "cam-1");
    await flushPromises();
    expect(wrapper.find('[data-testid="clear-filters"]').exists()).toBe(true);

    await wrapper.find('[data-testid="clear-filters"]').trigger("click");
    await flushPromises();

    expect(wrapper.find('[data-testid="clear-filters"]').exists()).toBe(false);
    expect(mockedClips).toHaveBeenLastCalledWith(
      expect.objectContaining({ camera_id: undefined, since: undefined, until: undefined }),
    );
  });

  it("pre-filters by camera when landing from a ?camera_id= link", async () => {
    mockedStatus.mockResolvedValue(linkedStatus());
    mockedClips.mockResolvedValue(clipsResponse([makeClip()], 1));
    const router = makeRouter();
    await router.push("/?camera_id=cam-2");
    const pinia = makePinia();
    useAuthStore().user = { ...fakeUser, is_superuser: true };
    const wrapper = mount(LibraryView, { global: mountGlobal(pinia, router) });
    await flushPromises();

    expect(mockedClips).toHaveBeenCalledWith(
      expect.objectContaining({ camera_id: "cam-2", page: 1 }),
    );
    expect(wrapper.find('[data-testid="clear-filters"]').exists()).toBe(true);
  });
});

describe("LibraryView — recognized person filter", () => {
  beforeEach(() => {
    mockedStatus.mockResolvedValue(linkedStatus());
    mockedPeople.mockResolvedValue([
      {
        id: "p-1",
        name: "Alex",
        never_mark_suspicious: false,
        has_thumbnail: false,
        face_count: 1,
        created_at: "",
        updated_at: "",
      },
      {
        id: "p-2",
        name: "Sam",
        never_mark_suspicious: false,
        has_thumbnail: false,
        face_count: 1,
        created_at: "",
        updated_at: "",
      },
    ]);
  });

  it("omits the filter dropdown when nobody has been enrolled", async () => {
    mockedPeople.mockResolvedValue([]);
    mockedClips.mockResolvedValue(clipsResponse([]));
    const { wrapper } = await mountLibrary();
    expect(wrapper.find('[data-testid="recognized-person-filter"]').exists()).toBe(false);
  });

  it("reloads filtered to the chosen person and shows the clear-filters button", async () => {
    mockedClips
      .mockResolvedValueOnce(clipsResponse([makeClip()], 1))
      .mockResolvedValueOnce(clipsResponse([], 0));
    const { wrapper } = await mountLibrary();
    expect(wrapper.find('[data-testid="clear-filters"]').exists()).toBe(false);

    const selects = wrapper.findAllComponents({ name: "Select" });
    await selects[1]!.vm.$emit("update:modelValue", "p-1");
    await flushPromises();

    expect(mockedClips).toHaveBeenLastCalledWith(
      expect.objectContaining({ recognized_person_id: "p-1", page: 1 }),
    );
    expect(wrapper.find('[data-testid="clear-filters"]').exists()).toBe(true);
  });

  it("clears the recognized-person filter along with the rest via the toolbar button", async () => {
    mockedClips.mockResolvedValue(clipsResponse([makeClip()], 1));
    const { wrapper } = await mountLibrary();

    const selects = wrapper.findAllComponents({ name: "Select" });
    await selects[1]!.vm.$emit("update:modelValue", "p-2");
    await flushPromises();
    expect(wrapper.find('[data-testid="clear-filters"]').exists()).toBe(true);

    await wrapper.find('[data-testid="clear-filters"]').trigger("click");
    await flushPromises();

    expect(wrapper.find('[data-testid="clear-filters"]').exists()).toBe(false);
    expect(mockedClips).toHaveBeenLastCalledWith(
      expect.objectContaining({ recognized_person_id: undefined }),
    );
  });
});

describe("LibraryView — selection", () => {
  beforeEach(() => {
    mockedStatus.mockResolvedValue(linkedStatus());
  });

  it("selects everything on the page and shows the bulk bar with a count", async () => {
    mockedClips.mockResolvedValue(
      clipsResponse([makeClip({ id: "clip-1" }), makeClip({ id: "clip-2", camera_id: "cam-2" })], 2),
    );
    const { wrapper } = await mountLibrary();
    expect(wrapper.find('[data-testid="bulk-bar"]').exists()).toBe(false);

    await wrapper.findComponent({ name: "Checkbox" }).vm.$emit("update:modelValue", true);
    await flushPromises();
    expect(wrapper.find('[data-testid="bulk-bar"]').text()).toContain("2 selected");
  });

  it("toggles an individual clip's selection from its card", async () => {
    mockedClips.mockResolvedValue(clipsResponse([makeClip({ id: "clip-1" })], 1));
    const { wrapper } = await mountLibrary();

    await wrapper.findComponent(ClipCard).vm.$emit("update:selected", true);
    await flushPromises();
    expect(wrapper.find('[data-testid="bulk-bar"]').text()).toContain("1 selected");

    await wrapper.findComponent(ClipCard).vm.$emit("update:selected", false);
    await flushPromises();
    expect(wrapper.find('[data-testid="bulk-bar"]').exists()).toBe(false);
  });

  it("un-checking select-all clears the selection", async () => {
    mockedClips.mockResolvedValue(clipsResponse([makeClip({ id: "clip-1" })], 1));
    const { wrapper } = await mountLibrary();

    await wrapper.findComponent({ name: "Checkbox" }).vm.$emit("update:modelValue", true);
    await flushPromises();
    expect(wrapper.find('[data-testid="bulk-bar"]').exists()).toBe(true);

    await wrapper.findComponent({ name: "Checkbox" }).vm.$emit("update:modelValue", false);
    await flushPromises();
    expect(wrapper.find('[data-testid="bulk-bar"]').exists()).toBe(false);
  });

  it("clears the selection via the bulk bar's Clear button", async () => {
    mockedClips.mockResolvedValue(clipsResponse([makeClip({ id: "clip-1" })], 1));
    const { wrapper } = await mountLibrary();
    await wrapper.findComponent(ClipCard).vm.$emit("update:selected", true);
    await flushPromises();

    const clearButton = wrapper.findAll("button").find((b) => b.text() === "Clear")!;
    await clearButton.trigger("click");
    expect(wrapper.find('[data-testid="bulk-bar"]').exists()).toBe(false);
  });

  it("resets the selection whenever a filter changes", async () => {
    mockedClips.mockResolvedValue(clipsResponse([makeClip({ id: "clip-1" })], 1));
    const { wrapper } = await mountLibrary();
    await wrapper.findComponent(ClipCard).vm.$emit("update:selected", true);
    await flushPromises();
    expect(wrapper.find('[data-testid="bulk-bar"]').exists()).toBe(true);

    await wrapper.findComponent({ name: "Select" }).vm.$emit("update:modelValue", "cam-1");
    await flushPromises();
    expect(wrapper.find('[data-testid="bulk-bar"]').exists()).toBe(false);
  });
});

describe("LibraryView — bulk download", () => {
  beforeEach(async () => {
    mockedStatus.mockResolvedValue(linkedStatus());
    mockedClips.mockResolvedValue(clipsResponse([makeClip({ id: "clip-1" })], 1));
  });

  it("downloads the selected clips as a zip", async () => {
    mockedDownloadZip.mockResolvedValue(undefined);
    const { wrapper } = await mountLibrary();
    await wrapper.findComponent(ClipCard).vm.$emit("update:selected", true);
    await flushPromises();

    await wrapper.find('[data-testid="bulk-download"]').trigger("click");
    await flushPromises();
    expect(mockedDownloadZip).toHaveBeenCalledWith(["clip-1"]);
  });

  it("shows an error toast with the API message when the zip download fails", async () => {
    mockedDownloadZip.mockRejectedValue(new ApiError(500, "Storage unavailable."));
    const { wrapper } = await mountLibrary();
    await wrapper.findComponent(ClipCard).vm.$emit("update:selected", true);
    await flushPromises();

    await wrapper.find('[data-testid="bulk-download"]').trigger("click");
    await flushPromises();
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({
        severity: "error",
        summary: "Download failed",
        detail: "Storage unavailable.",
      }),
    );
  });

  it("shows a generic error detail when the zip download fails with a non-API error", async () => {
    mockedDownloadZip.mockRejectedValue(new TypeError("boom"));
    const { wrapper } = await mountLibrary();
    await wrapper.findComponent(ClipCard).vm.$emit("update:selected", true);
    await flushPromises();

    await wrapper.find('[data-testid="bulk-download"]').trigger("click");
    await flushPromises();
    expect(toastAdd).toHaveBeenCalledWith(expect.objectContaining({ detail: "Unexpected error." }));
  });
});

describe("LibraryView — bulk analyze", () => {
  beforeEach(async () => {
    mockedStatus.mockResolvedValue(linkedStatus());
    mockedClips.mockResolvedValue(clipsResponse([makeClip({ id: "clip-1" })], 1));
  });

  it("queues the selected clips for analysis, toasts success, and clears selection", async () => {
    mockedBulkAnalyze.mockResolvedValue({ succeeded: 1, failed: 0 });
    const { wrapper } = await mountLibrary();
    await wrapper.findComponent(ClipCard).vm.$emit("update:selected", true);
    await flushPromises();

    await wrapper.find('[data-testid="bulk-analyze"]').trigger("click");
    await flushPromises();

    expect(mockedBulkAnalyze).toHaveBeenCalledWith(["clip-1"]);
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({
        severity: "success",
        summary: "Queued 1 clip(s) for analysis",
        detail: undefined,
      }),
    );
    expect(wrapper.find('[data-testid="bulk-bar"]').exists()).toBe(false);
  });

  it("shows a warning toast when some clips can't be queued (not downloaded yet)", async () => {
    mockedBulkAnalyze.mockResolvedValue({ succeeded: 0, failed: 1 });
    const { wrapper } = await mountLibrary();
    await wrapper.findComponent(ClipCard).vm.$emit("update:selected", true);
    await flushPromises();

    await wrapper.find('[data-testid="bulk-analyze"]').trigger("click");
    await flushPromises();

    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "warn", detail: "1 could not be queued." }),
    );
  });

  it("shows an error toast with the API message when the request itself fails", async () => {
    mockedBulkAnalyze.mockRejectedValue(new ApiError(500, "Server exploded."));
    const { wrapper } = await mountLibrary();
    await wrapper.findComponent(ClipCard).vm.$emit("update:selected", true);
    await flushPromises();

    await wrapper.find('[data-testid="bulk-analyze"]').trigger("click");
    await flushPromises();

    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({
        severity: "error",
        summary: "Bulk analyze failed",
        detail: "Server exploded.",
      }),
    );
  });

  it("shows a generic error detail when the request fails with a non-API error", async () => {
    mockedBulkAnalyze.mockRejectedValue(new TypeError("boom"));
    const { wrapper } = await mountLibrary();
    await wrapper.findComponent(ClipCard).vm.$emit("update:selected", true);
    await flushPromises();

    await wrapper.find('[data-testid="bulk-analyze"]').trigger("click");
    await flushPromises();

    expect(toastAdd).toHaveBeenCalledWith(expect.objectContaining({ detail: "Unexpected error." }));
  });
});

describe("LibraryView — bulk archive", () => {
  beforeEach(async () => {
    mockedStatus.mockResolvedValue(linkedStatus());
    mockedClips.mockResolvedValue(clipsResponse([makeClip({ id: "clip-1" })], 1));
  });

  it("hides the archive picker and button when no cloud backend is connected", async () => {
    const { wrapper } = await mountLibrary();
    await wrapper.findComponent(ClipCard).vm.$emit("update:selected", true);
    await flushPromises();
    expect(wrapper.find('[data-testid="bulk-archive-destination"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="bulk-archive"]').exists()).toBe(false);
  });

  it("also hides the archive picker if the integration settings fetch fails", async () => {
    mockedIntegrationSettings.mockRejectedValue(new ApiError(500, "boom"));
    const { wrapper } = await mountLibrary();
    await wrapper.findComponent(ClipCard).vm.$emit("update:selected", true);
    await flushPromises();
    expect(wrapper.find('[data-testid="bulk-archive-destination"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="bulk-archive"]').exists()).toBe(false);
  });

  it("offers only connected backends in the archive destination picker", async () => {
    mockedIntegrationSettings.mockResolvedValue(
      fakeStorageIntegrationSettings({
        s3_enabled: true,
        s3_credentials_set: true,
        onedrive_enabled: true,
        onedrive_connected: true,
      }),
    );
    const { wrapper } = await mountLibrary();
    await wrapper.findComponent(ClipCard).vm.$emit("update:selected", true);
    await flushPromises();
    const select = selectByTestId(wrapper, "bulk-archive-destination");
    expect(select.props("options")).toEqual([
      { label: "Amazon S3", value: "s3" },
      { label: "Microsoft OneDrive", value: "onedrive" },
    ]);
  });

  it("archives the selected clips to the default (first connected) backend and clears selection", async () => {
    mockedIntegrationSettings.mockResolvedValue(
      fakeStorageIntegrationSettings({ s3_enabled: true, s3_credentials_set: true }),
    );
    mockedArchiveClips.mockResolvedValue({ succeeded: 1, failed: 0 });
    const { wrapper } = await mountLibrary();
    await wrapper.findComponent(ClipCard).vm.$emit("update:selected", true);
    await flushPromises();

    await wrapper.find('[data-testid="bulk-archive"]').trigger("click");
    await flushPromises();

    expect(mockedArchiveClips).toHaveBeenCalledWith(["clip-1"], "s3");
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "success", summary: "Queued 1 clip(s) to archive" }),
    );
    expect(wrapper.find('[data-testid="bulk-bar"]').exists()).toBe(false);
  });

  it("archives to whichever backend is chosen in the picker", async () => {
    mockedIntegrationSettings.mockResolvedValue(
      fakeStorageIntegrationSettings({
        s3_enabled: true,
        s3_credentials_set: true,
        google_drive_enabled: true,
        google_drive_connected: true,
      }),
    );
    mockedArchiveClips.mockResolvedValue({ succeeded: 1, failed: 0 });
    const { wrapper } = await mountLibrary();
    await wrapper.findComponent(ClipCard).vm.$emit("update:selected", true);
    await flushPromises();

    await selectByTestId(wrapper, "bulk-archive-destination").vm.$emit(
      "update:modelValue",
      "google_drive",
    );
    await wrapper.find('[data-testid="bulk-archive"]').trigger("click");
    await flushPromises();

    expect(mockedArchiveClips).toHaveBeenCalledWith(["clip-1"], "google_drive");
  });

  it("shows a warning toast when some clips can't be archived", async () => {
    mockedIntegrationSettings.mockResolvedValue(
      fakeStorageIntegrationSettings({ s3_enabled: true, s3_credentials_set: true }),
    );
    mockedArchiveClips.mockResolvedValue({ succeeded: 0, failed: 1 });
    const { wrapper } = await mountLibrary();
    await wrapper.findComponent(ClipCard).vm.$emit("update:selected", true);
    await flushPromises();

    await wrapper.find('[data-testid="bulk-archive"]').trigger("click");
    await flushPromises();

    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "warn", detail: "1 could not be queued." }),
    );
  });

  it("shows an error toast with the API message when the archive request fails", async () => {
    mockedIntegrationSettings.mockResolvedValue(
      fakeStorageIntegrationSettings({ s3_enabled: true, s3_credentials_set: true }),
    );
    mockedArchiveClips.mockRejectedValue(new ApiError(400, "s3 is not configured."));
    const { wrapper } = await mountLibrary();
    await wrapper.findComponent(ClipCard).vm.$emit("update:selected", true);
    await flushPromises();

    await wrapper.find('[data-testid="bulk-archive"]').trigger("click");
    await flushPromises();

    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({
        severity: "error",
        summary: "Archive failed",
        detail: "s3 is not configured.",
      }),
    );
  });

  it("shows a generic error detail when the archive request fails with a non-API error", async () => {
    mockedIntegrationSettings.mockResolvedValue(
      fakeStorageIntegrationSettings({ s3_enabled: true, s3_credentials_set: true }),
    );
    mockedArchiveClips.mockRejectedValue(new TypeError("boom"));
    const { wrapper } = await mountLibrary();
    await wrapper.findComponent(ClipCard).vm.$emit("update:selected", true);
    await flushPromises();

    await wrapper.find('[data-testid="bulk-archive"]').trigger("click");
    await flushPromises();

    expect(toastAdd).toHaveBeenCalledWith(expect.objectContaining({ detail: "Unexpected error." }));
  });
});

describe("LibraryView — bulk restore", () => {
  beforeEach(async () => {
    mockedStatus.mockResolvedValue(linkedStatus());
    mockedClips.mockResolvedValue(clipsResponse([makeClip({ id: "clip-1" })], 1));
  });

  it("is always available, even with no cloud backend connected", async () => {
    const { wrapper } = await mountLibrary();
    await wrapper.findComponent(ClipCard).vm.$emit("update:selected", true);
    await flushPromises();
    expect(wrapper.find('[data-testid="bulk-restore"]').exists()).toBe(true);
  });

  it("restores the selected clips, toasts success, and clears selection", async () => {
    mockedRestoreClips.mockResolvedValue({ succeeded: 1, failed: 0 });
    const { wrapper } = await mountLibrary();
    await wrapper.findComponent(ClipCard).vm.$emit("update:selected", true);
    await flushPromises();

    await wrapper.find('[data-testid="bulk-restore"]').trigger("click");
    await flushPromises();

    expect(mockedRestoreClips).toHaveBeenCalledWith(["clip-1"]);
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "success", summary: "Queued 1 clip(s) to restore" }),
    );
    expect(wrapper.find('[data-testid="bulk-bar"]').exists()).toBe(false);
  });

  it("shows a warning toast when some clips were already local", async () => {
    mockedRestoreClips.mockResolvedValue({ succeeded: 0, failed: 1 });
    const { wrapper } = await mountLibrary();
    await wrapper.findComponent(ClipCard).vm.$emit("update:selected", true);
    await flushPromises();

    await wrapper.find('[data-testid="bulk-restore"]').trigger("click");
    await flushPromises();

    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "warn", detail: "1 were already local." }),
    );
  });

  it("shows an error toast with the API message when the restore request fails", async () => {
    mockedRestoreClips.mockRejectedValue(new ApiError(500, "Server exploded."));
    const { wrapper } = await mountLibrary();
    await wrapper.findComponent(ClipCard).vm.$emit("update:selected", true);
    await flushPromises();

    await wrapper.find('[data-testid="bulk-restore"]').trigger("click");
    await flushPromises();

    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({
        severity: "error",
        summary: "Restore failed",
        detail: "Server exploded.",
      }),
    );
  });

  it("shows a generic error detail when the restore request fails with a non-API error", async () => {
    mockedRestoreClips.mockRejectedValue(new TypeError("boom"));
    const { wrapper } = await mountLibrary();
    await wrapper.findComponent(ClipCard).vm.$emit("update:selected", true);
    await flushPromises();

    await wrapper.find('[data-testid="bulk-restore"]').trigger("click");
    await flushPromises();

    expect(toastAdd).toHaveBeenCalledWith(expect.objectContaining({ detail: "Unexpected error." }));
  });
});

describe("LibraryView — bulk delete", () => {
  beforeEach(async () => {
    mockedStatus.mockResolvedValue(linkedStatus());
  });

  it("confirms, performs the delete, toasts success, clears selection, and reloads", async () => {
    mockedClips
      .mockResolvedValueOnce(clipsResponse([makeClip({ id: "clip-1" })], 1))
      .mockResolvedValueOnce(clipsResponse([], 0));
    mockedBulkDelete.mockResolvedValue({ succeeded: 1, failed: 0 });
    const { wrapper } = await mountLibrary();
    await wrapper.findComponent(ClipCard).vm.$emit("update:selected", true);
    await flushPromises();

    await wrapper.find('[data-testid="bulk-delete"]').trigger("click");
    expect(confirmRequire).toHaveBeenCalledWith(
      expect.objectContaining({
        header: "Delete clips",
        message: "Delete 1 clip(s)? This cannot be undone.",
      }),
    );

    acceptLastConfirm();
    await flushPromises();

    expect(mockedBulkDelete).toHaveBeenCalledWith(["clip-1"]);
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "success", summary: "Deleted 1 clip(s)", detail: undefined }),
    );
    expect(wrapper.find('[data-testid="bulk-bar"]').exists()).toBe(false);
    // One initial loadClips + one for the recognized-count badge + one reload.
    expect(mockedClips).toHaveBeenCalledTimes(3);
  });

  it("shows a warning toast when some deletes fail", async () => {
    mockedClips.mockResolvedValue(clipsResponse([makeClip({ id: "clip-1" })], 1));
    mockedBulkDelete.mockResolvedValue({ succeeded: 1, failed: 1 });
    const { wrapper } = await mountLibrary();
    await wrapper.findComponent(ClipCard).vm.$emit("update:selected", true);
    await flushPromises();

    await wrapper.find('[data-testid="bulk-delete"]').trigger("click");
    acceptLastConfirm();
    await flushPromises();

    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "warn", detail: "1 could not be deleted." }),
    );
  });

  it("shows an error toast with the API message when the bulk delete request itself fails", async () => {
    mockedClips.mockResolvedValue(clipsResponse([makeClip({ id: "clip-1" })], 1));
    mockedBulkDelete.mockRejectedValue(new ApiError(500, "Server exploded."));
    const { wrapper } = await mountLibrary();
    await wrapper.findComponent(ClipCard).vm.$emit("update:selected", true);
    await flushPromises();

    await wrapper.find('[data-testid="bulk-delete"]').trigger("click");
    acceptLastConfirm();
    await flushPromises();

    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({
        severity: "error",
        summary: "Bulk delete failed",
        detail: "Server exploded.",
      }),
    );
  });

  it("shows a generic error detail when the bulk delete request fails with a non-API error", async () => {
    mockedClips.mockResolvedValue(clipsResponse([makeClip({ id: "clip-1" })], 1));
    mockedBulkDelete.mockRejectedValue(new TypeError("boom"));
    const { wrapper } = await mountLibrary();
    await wrapper.findComponent(ClipCard).vm.$emit("update:selected", true);
    await flushPromises();

    await wrapper.find('[data-testid="bulk-delete"]').trigger("click");
    acceptLastConfirm();
    await flushPromises();

    expect(toastAdd).toHaveBeenCalledWith(expect.objectContaining({ detail: "Unexpected error." }));
  });
});

describe("LibraryView — pagination", () => {
  it("requests the next page when the paginator emits a page change", async () => {
    mockedStatus.mockResolvedValue(linkedStatus());
    mockedClips.mockResolvedValue(clipsResponse([makeClip({ id: "clip-1" })], 50));
    const { wrapper } = await mountLibrary();

    await wrapper
      .findComponent({ name: "Paginator" })
      .vm.$emit("page", { first: 24, rows: 24, page: 1 });
    await flushPromises();

    expect(mockedClips).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2 }));
  });
});

describe("LibraryView — clip detail modal", () => {
  beforeEach(() => {
    mockedStatus.mockResolvedValue(linkedStatus());
  });

  it("opens the detail modal for the clicked clip", async () => {
    mockedClips.mockResolvedValue(clipsResponse([makeClip({ id: "clip-1", camera_id: "cam-2" })], 1));
    const { wrapper } = await mountLibrary();
    expect(wrapper.findComponent(ClipDetailModal).props("clip")).toBeNull();

    await wrapper.findComponent(ClipCard).vm.$emit("open");
    await flushPromises();

    const modal = wrapper.findComponent(ClipDetailModal);
    expect(modal.props("clip")?.id).toBe("clip-1");
    expect(modal.props("cameraName")).toBe("Backyard");
  });

  it("closes the modal when it emits close", async () => {
    mockedClips.mockResolvedValue(clipsResponse([makeClip({ id: "clip-1" })], 1));
    const { wrapper } = await mountLibrary();
    await wrapper.findComponent(ClipCard).vm.$emit("open");
    await flushPromises();
    expect(wrapper.findComponent(ClipDetailModal).props("clip")).not.toBeNull();

    await wrapper.findComponent(ClipDetailModal).vm.$emit("close");
    expect(wrapper.findComponent(ClipDetailModal).props("clip")).toBeNull();
  });

  it("confirms and deletes the open clip, then closes the modal, toasts, and reloads", async () => {
    mockedClips
      .mockResolvedValueOnce(clipsResponse([makeClip({ id: "clip-1" })], 1))
      .mockResolvedValueOnce(clipsResponse([], 0));
    mockedDeleteClip.mockResolvedValue(undefined);
    const { wrapper } = await mountLibrary();
    await wrapper.findComponent(ClipCard).vm.$emit("open");
    await flushPromises();

    await wrapper.findComponent(ClipDetailModal).vm.$emit("delete");
    expect(confirmRequire).toHaveBeenCalledWith(
      expect.objectContaining({
        header: "Delete clip",
        message: "Delete this clip? This cannot be undone.",
      }),
    );

    acceptLastConfirm();
    await flushPromises();

    expect(mockedDeleteClip).toHaveBeenCalledWith("clip-1");
    expect(wrapper.findComponent(ClipDetailModal).props("clip")).toBeNull();
    expect(toastAdd).toHaveBeenCalledWith(expect.objectContaining({ summary: "Clip deleted" }));
    // One initial loadClips + one for the recognized-count badge + one reload.
    expect(mockedClips).toHaveBeenCalledTimes(3);
  });

  it("shows an error toast and keeps the modal open when the single delete fails", async () => {
    mockedClips.mockResolvedValue(clipsResponse([makeClip({ id: "clip-1" })], 1));
    mockedDeleteClip.mockRejectedValue(new ApiError(500, "Could not reach storage."));
    const { wrapper } = await mountLibrary();
    await wrapper.findComponent(ClipCard).vm.$emit("open");
    await flushPromises();

    await wrapper.findComponent(ClipDetailModal).vm.$emit("delete");
    acceptLastConfirm();
    await flushPromises();

    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({
        severity: "error",
        summary: "Could not delete clip",
        detail: "Could not reach storage.",
      }),
    );
    expect(wrapper.findComponent(ClipDetailModal).props("clip")?.id).toBe("clip-1");
  });

  it("shows a generic error detail when the single delete fails with a non-API error", async () => {
    mockedClips.mockResolvedValue(clipsResponse([makeClip({ id: "clip-1" })], 1));
    mockedDeleteClip.mockRejectedValue(new TypeError("boom"));
    const { wrapper } = await mountLibrary();
    await wrapper.findComponent(ClipCard).vm.$emit("open");
    await flushPromises();

    await wrapper.findComponent(ClipDetailModal).vm.$emit("delete");
    acceptLastConfirm();
    await flushPromises();

    expect(toastAdd).toHaveBeenCalledWith(expect.objectContaining({ detail: "Unexpected error." }));
  });
});

describe("LibraryView — clip modal prev/next", () => {
  beforeEach(() => {
    mockedStatus.mockResolvedValue(linkedStatus());
  });

  it("disables prev on the first clip and enables next when a sibling exists", async () => {
    mockedClips.mockResolvedValue(clipsResponse(makeClips(3), 3));
    const { wrapper } = await mountLibrary();

    await wrapper.findAllComponents(ClipCard)[0]!.vm.$emit("open");
    await flushPromises();

    const modal = wrapper.findComponent(ClipDetailModal);
    expect(modal.props("hasPrev")).toBe(false);
    expect(modal.props("hasNext")).toBe(true);
  });

  it("disables next on the last clip of the last page", async () => {
    mockedClips.mockResolvedValue(clipsResponse(makeClips(3), 3));
    const { wrapper } = await mountLibrary();

    await wrapper.findAllComponents(ClipCard)[2]!.vm.$emit("open");
    await flushPromises();

    const modal = wrapper.findComponent(ClipDetailModal);
    expect(modal.props("hasPrev")).toBe(true);
    expect(modal.props("hasNext")).toBe(false);
  });

  it("moves to the next clip on the same page", async () => {
    mockedClips.mockResolvedValue(clipsResponse(makeClips(3), 3));
    const { wrapper } = await mountLibrary();
    await wrapper.findAllComponents(ClipCard)[0]!.vm.$emit("open");
    await flushPromises();

    await wrapper.findComponent(ClipDetailModal).vm.$emit("next");
    await flushPromises();

    expect(wrapper.findComponent(ClipDetailModal).props("clip")?.id).toBe("clip-2");
  });

  it("moves to the previous clip on the same page", async () => {
    mockedClips.mockResolvedValue(clipsResponse(makeClips(3), 3));
    const { wrapper } = await mountLibrary();
    await wrapper.findAllComponents(ClipCard)[1]!.vm.$emit("open");
    await flushPromises();

    await wrapper.findComponent(ClipDetailModal).vm.$emit("prev");
    await flushPromises();

    expect(wrapper.findComponent(ClipDetailModal).props("clip")?.id).toBe("clip-1");
  });

  it("crosses forward into the next page without disturbing the visible grid", async () => {
    const page1 = clipsResponse(makeClips(24, 1), 25, 1);
    const page2 = clipsResponse(makeClips(1, 25), 25, 2);
    mockedClips.mockImplementation(pagedClipsMock({ 1: page1, 2: page2 }));
    const { wrapper } = await mountLibrary();
    const callsBeforeCrossing = mockedClips.mock.calls.length;

    await wrapper.findAllComponents(ClipCard)[23]!.vm.$emit("open");
    await flushPromises();
    expect(wrapper.findComponent(ClipDetailModal).props("hasNext")).toBe(true);

    await wrapper.findComponent(ClipDetailModal).vm.$emit("next");
    await flushPromises();

    expect(wrapper.findComponent(ClipDetailModal).props("clip")?.id).toBe("clip-25");
    expect(mockedClips).toHaveBeenCalledWith(expect.objectContaining({ page: 2 }));
    expect(mockedClips.mock.calls.length).toBeGreaterThan(callsBeforeCrossing);
    // The grid itself never moved off page 1.
    expect(wrapper.findComponent({ name: "Paginator" }).props("first")).toBe(0);
    expect(wrapper.findAllComponents(ClipCard)).toHaveLength(24);
    expect(wrapper.findAllComponents(ClipCard)[0]!.props("clip").id).toBe("clip-1");
  });

  it("continues navigating within an already-fetched adjacent page without refetching", async () => {
    const page1 = clipsResponse(makeClips(24, 1), 26, 1);
    const page2 = clipsResponse(makeClips(2, 25), 26, 2);
    mockedClips.mockImplementation(pagedClipsMock({ 1: page1, 2: page2 }));
    const { wrapper } = await mountLibrary();

    await wrapper.findAllComponents(ClipCard)[23]!.vm.$emit("open");
    await flushPromises();
    await wrapper.findComponent(ClipDetailModal).vm.$emit("next");
    await flushPromises();
    expect(wrapper.findComponent(ClipDetailModal).props("clip")?.id).toBe("clip-25");
    const callsAfterCrossing = mockedClips.mock.calls.length;

    await wrapper.findComponent(ClipDetailModal).vm.$emit("next");
    await flushPromises();

    expect(wrapper.findComponent(ClipDetailModal).props("clip")?.id).toBe("clip-26");
    expect(mockedClips.mock.calls.length).toBe(callsAfterCrossing);
  });

  it("crosses backward into the previous page, landing on its last clip", async () => {
    const page1 = clipsResponse(makeClips(24, 1), 25, 1);
    const page2 = clipsResponse(makeClips(1, 25), 25, 2);
    mockedClips.mockImplementation(pagedClipsMock({ 1: page1, 2: page2 }));
    const { wrapper } = await mountLibrary();

    await wrapper.findComponent({ name: "Paginator" }).vm.$emit("page", { page: 1 });
    await flushPromises();
    await wrapper.findAllComponents(ClipCard)[0]!.vm.$emit("open");
    await flushPromises();
    expect(wrapper.findComponent(ClipDetailModal).props("hasPrev")).toBe(true);

    await wrapper.findComponent(ClipDetailModal).vm.$emit("prev");
    await flushPromises();

    expect(wrapper.findComponent(ClipDetailModal).props("clip")?.id).toBe("clip-24");
    expect(mockedClips).toHaveBeenCalledWith(expect.objectContaining({ page: 1 }));
    // The grid itself never moved off page 2.
    expect(wrapper.findComponent({ name: "Paginator" }).props("first")).toBe(24);
  });

  it("shows an error toast and keeps the current clip when the boundary fetch fails", async () => {
    mockedClips.mockImplementation(async (params: ClipListParams = {}) => {
      if (params.has_recognized_person) return clipsResponse([], 0);
      if ((params.page ?? 1) === 2) throw new ApiError(500, "Server exploded.");
      return clipsResponse(makeClips(24, 1), 25, 1);
    });
    const { wrapper } = await mountLibrary();
    await wrapper.findAllComponents(ClipCard)[23]!.vm.$emit("open");
    await flushPromises();

    await wrapper.findComponent(ClipDetailModal).vm.$emit("next");
    await flushPromises();

    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({
        severity: "error",
        summary: "Could not load the next clip",
        detail: "Server exploded.",
      }),
    );
    expect(wrapper.findComponent(ClipDetailModal).props("clip")?.id).toBe("clip-24");
  });

  it("shows a generic error detail when the boundary fetch fails with a non-API error", async () => {
    mockedClips.mockImplementation(async (params: ClipListParams = {}) => {
      if (params.has_recognized_person) return clipsResponse([], 0);
      if ((params.page ?? 1) === 2) throw new TypeError("boom");
      return clipsResponse(makeClips(24, 1), 25, 1);
    });
    const { wrapper } = await mountLibrary();
    await wrapper.findAllComponents(ClipCard)[23]!.vm.$emit("open");
    await flushPromises();

    await wrapper.findComponent(ClipDetailModal).vm.$emit("next");
    await flushPromises();

    expect(toastAdd).toHaveBeenCalledWith(expect.objectContaining({ detail: "Unexpected error." }));
  });

  it("does nothing if the boundary page unexpectedly comes back empty", async () => {
    mockedClips.mockImplementation(async (params: ClipListParams = {}) => {
      if (params.has_recognized_person) return clipsResponse([], 0);
      if ((params.page ?? 1) === 2) return clipsResponse([], 25, 2);
      return clipsResponse(makeClips(24, 1), 25, 1);
    });
    const { wrapper } = await mountLibrary();
    await wrapper.findAllComponents(ClipCard)[23]!.vm.$emit("open");
    await flushPromises();

    await wrapper.findComponent(ClipDetailModal).vm.$emit("next");
    await flushPromises();

    expect(wrapper.findComponent(ClipDetailModal).props("clip")?.id).toBe("clip-24");
    expect(toastAdd).not.toHaveBeenCalled();
  });

  it("re-anchors to the grid's own list after the modal is closed and reopened", async () => {
    const page1 = clipsResponse(makeClips(24, 1), 25, 1);
    const page2 = clipsResponse(makeClips(1, 25), 25, 2);
    mockedClips.mockImplementation(pagedClipsMock({ 1: page1, 2: page2 }));
    const { wrapper } = await mountLibrary();
    await wrapper.findAllComponents(ClipCard)[23]!.vm.$emit("open");
    await flushPromises();
    await wrapper.findComponent(ClipDetailModal).vm.$emit("next");
    await flushPromises();
    expect(wrapper.findComponent(ClipDetailModal).props("clip")?.id).toBe("clip-25");

    await wrapper.findComponent(ClipDetailModal).vm.$emit("close");
    await flushPromises();
    await wrapper.findAllComponents(ClipCard)[0]!.vm.$emit("open");
    await flushPromises();

    const modal = wrapper.findComponent(ClipDetailModal);
    expect(modal.props("clip")?.id).toBe("clip-1");
    expect(modal.props("hasPrev")).toBe(false);
  });

  it("re-anchors to the grid's own list after deleting an overridden clip", async () => {
    const page1 = clipsResponse(makeClips(24, 1), 25, 1);
    const page2 = clipsResponse(makeClips(1, 25), 25, 2);
    mockedClips.mockImplementation(pagedClipsMock({ 1: page1, 2: page2 }));
    mockedDeleteClip.mockResolvedValue(undefined);
    const { wrapper } = await mountLibrary();
    await wrapper.findAllComponents(ClipCard)[23]!.vm.$emit("open");
    await flushPromises();
    await wrapper.findComponent(ClipDetailModal).vm.$emit("next");
    await flushPromises();
    expect(wrapper.findComponent(ClipDetailModal).props("clip")?.id).toBe("clip-25");

    await wrapper.findComponent(ClipDetailModal).vm.$emit("delete");
    acceptLastConfirm();
    await flushPromises();
    await wrapper.findAllComponents(ClipCard)[0]!.vm.$emit("open");
    await flushPromises();

    const modal = wrapper.findComponent(ClipDetailModal);
    expect(modal.props("clip")?.id).toBe("clip-1");
    expect(modal.props("hasPrev")).toBe(false);
  });
});

describe("LibraryView — viewer account (read-only)", () => {
  it("shows clips but no selection, bulk actions, download, or delete", async () => {
    mockedStatus.mockResolvedValue(linkedStatus());
    mockedClips.mockResolvedValue(clipsResponse([makeClip({ id: "clip-1" })], 1));
    const { wrapper } = await mountLibrary(false);

    expect(wrapper.find('[data-testid="clip-grid"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="select-all"]').exists()).toBe(false);
    expect(wrapper.findComponent(ClipCard).props("selectable")).toBe(false);

    await wrapper.findComponent(ClipCard).vm.$emit("open");
    await flushPromises();
    expect(wrapper.findComponent(ClipDetailModal).props("canManage")).toBe(false);
  });
});

describe("LibraryView — recognized-only stat and toggle", () => {
  function withRecognizedTotal(total: number) {
    mockedClips.mockImplementation(async (params: ClipListParams = {}) => {
      if (params.has_recognized_person) {
        return clipsResponse([], total);
      }
      return clipsResponse([makeClip()], 1);
    });
  }

  it("hides the toggle when there are no recognized clips at all", async () => {
    withRecognizedTotal(0);
    const { wrapper } = await mountLibrary();
    expect(wrapper.find('[data-testid="recognized-only-toggle"]').exists()).toBe(false);
  });

  it("shows the toggle with the recognized-clip count once it's non-zero", async () => {
    withRecognizedTotal(7);
    const { wrapper } = await mountLibrary();
    expect(wrapper.find('[data-testid="recognized-only-toggle"]').text()).toContain("7");
  });

  it("filters to has_recognized_person and clears the person-specific filter when toggled on", async () => {
    withRecognizedTotal(7);
    mockedPeople.mockResolvedValue([
      {
        id: "p-1",
        name: "Alex",
        never_mark_suspicious: false,
        has_thumbnail: false,
        face_count: 1,
        created_at: "",
        updated_at: "",
      },
    ]);
    const { wrapper } = await mountLibrary();

    const personSelect = wrapper.findAllComponents({ name: "Select" })[1]!;
    await personSelect.vm.$emit("update:modelValue", "p-1");
    await flushPromises();
    expect(mockedClips).toHaveBeenLastCalledWith(
      expect.objectContaining({ recognized_person_id: "p-1" }),
    );

    await wrapper.findComponent(ToggleButton).vm.$emit("update:modelValue", true);
    await flushPromises();

    expect(mockedClips).toHaveBeenLastCalledWith(
      expect.objectContaining({ has_recognized_person: true, recognized_person_id: undefined }),
    );
  });

  it("clears the toggle when a specific person is then chosen", async () => {
    withRecognizedTotal(7);
    mockedPeople.mockResolvedValue([
      {
        id: "p-1",
        name: "Alex",
        never_mark_suspicious: false,
        has_thumbnail: false,
        face_count: 1,
        created_at: "",
        updated_at: "",
      },
    ]);
    const { wrapper } = await mountLibrary();

    await wrapper.findComponent(ToggleButton).vm.$emit("update:modelValue", true);
    await flushPromises();
    const personSelect = wrapper.findAllComponents({ name: "Select" })[1]!;
    await personSelect.vm.$emit("update:modelValue", "p-1");
    await flushPromises();

    expect(mockedClips).toHaveBeenLastCalledWith(
      expect.objectContaining({ has_recognized_person: undefined, recognized_person_id: "p-1" }),
    );
    expect(wrapper.findComponent(ToggleButton).props("modelValue")).toBe(false);
  });

  it("resets the toggle via Clear filters", async () => {
    withRecognizedTotal(7);
    const { wrapper } = await mountLibrary();
    await wrapper.findComponent(ToggleButton).vm.$emit("update:modelValue", true);
    await flushPromises();

    await wrapper.find('[data-testid="clear-filters"]').trigger("click");
    await flushPromises();

    expect(wrapper.findComponent(ToggleButton).props("modelValue")).toBe(false);
  });
});
