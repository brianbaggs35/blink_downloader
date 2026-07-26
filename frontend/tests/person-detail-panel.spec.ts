import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  getPerson: vi.fn(),
  listPersonFaces: vi.fn(),
  updatePerson: vi.fn(),
  deleteFace: vi.fn(),
  deletePerson: vi.fn(),
  listCameras: vi.fn(),
  listClips: vi.fn(),
  detectFacesInClipFrame: vi.fn(),
  enrollFace: vi.fn(),
}));

const toastAdd = vi.fn();
vi.mock("primevue/usetoast", () => ({ useToast: () => ({ add: toastAdd }) }));

const confirmRequire = vi.fn();
vi.mock("primevue/useconfirm", () => ({ useConfirm: () => ({ require: confirmRequire }) }));

import {
  deleteFace,
  deletePerson,
  getPerson,
  listCameras,
  listClips,
  listPersonFaces,
  updatePerson,
} from "@/api";
import { ApiError } from "@/api/client";
import PersonDetailPanel from "@/components/PersonDetailPanel.vue";
import { useAuthStore } from "@/stores/auth";
import { fakeUser, makePinia, mountGlobal } from "./helpers";

import type { FaceEmbeddingRead, PersonRead } from "@/api";

const mockedGetPerson = vi.mocked(getPerson);
const mockedListFaces = vi.mocked(listPersonFaces);
const mockedUpdatePerson = vi.mocked(updatePerson);
const mockedDeleteFace = vi.mocked(deleteFace);
const mockedDeletePerson = vi.mocked(deletePerson);
const mockedCameras = vi.mocked(listCameras);
const mockedClips = vi.mocked(listClips);

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

function makeFace(overrides: Partial<FaceEmbeddingRead> = {}): FaceEmbeddingRead {
  return {
    id: "face-1",
    source_clip_id: "clip-1",
    source_frame_seconds: 5,
    created_at: "2026-07-20T00:01:00Z",
    ...overrides,
  };
}

async function mountPanel(personId = "p-1", isAdmin = true) {
  const pinia = makePinia();
  useAuthStore().user = { ...fakeUser, is_superuser: isAdmin };
  const wrapper = mount(PersonDetailPanel, {
    props: { personId },
    global: mountGlobal(pinia),
    attachTo: document.body,
  });
  await flushPromises();
  return wrapper;
}

beforeEach(() => {
  vi.clearAllMocks();
  mockedGetPerson.mockResolvedValue(makePerson());
  mockedListFaces.mockResolvedValue([makeFace()]);
  mockedCameras.mockResolvedValue([]);
  mockedClips.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 50 });
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("PersonDetailPanel loading", () => {
  it("shows a loading skeleton while fetching", () => {
    mockedGetPerson.mockReturnValue(new Promise(() => {}));
    const wrapper = mount(PersonDetailPanel, {
      props: { personId: "p-1" },
      global: mountGlobal(makePinia()),
    });
    expect(wrapper.find('[data-testid="person-detail-loading"]').exists()).toBe(true);
  });

  it("shows the API error message when loading fails", async () => {
    mockedGetPerson.mockRejectedValue(new ApiError(500, "Server exploded"));
    await mountPanel();
    expect(document.body.textContent).toContain("Server exploded");
  });

  it("falls back to a generic load error for non-API failures", async () => {
    mockedGetPerson.mockRejectedValue(new TypeError("down"));
    await mountPanel();
    expect(document.body.textContent).toContain("Could not load this person.");
  });

  it("re-loads when the personId prop changes", async () => {
    const wrapper = await mountPanel("p-1");
    expect(mockedGetPerson).toHaveBeenCalledWith("p-1");

    mockedGetPerson.mockResolvedValue(makePerson({ id: "p-2", name: "Sam" }));
    mockedListFaces.mockResolvedValue([]);
    await wrapper.setProps({ personId: "p-2" });
    await flushPromises();

    expect(mockedGetPerson).toHaveBeenCalledWith("p-2");
    expect(document.body.textContent).toContain("Sam");
  });
});

describe("PersonDetailPanel display", () => {
  it("shows the person's name and face count", async () => {
    mockedGetPerson.mockResolvedValue(makePerson({ name: "Jordan", face_count: 2 }));
    mockedListFaces.mockResolvedValue([makeFace(), makeFace({ id: "face-2" })]);
    await mountPanel();
    expect(document.body.textContent).toContain("Jordan");
    expect(document.body.textContent).toContain("2 enrolled face sample(s)");
  });

  it("shows an empty state with no face samples", async () => {
    mockedListFaces.mockResolvedValue([]);
    await mountPanel();
    expect(document.body.textContent).toContain("No face samples yet");
  });

  it("renders a face grid item per sample", async () => {
    mockedListFaces.mockResolvedValue([makeFace({ id: "face-1" }), makeFace({ id: "face-2" })]);
    await mountPanel();
    expect(document.body.querySelector('[data-testid="face-item-face-1"]')).toBeTruthy();
    expect(document.body.querySelector('[data-testid="face-item-face-2"]')).toBeTruthy();
  });

  it("hides rename/delete controls for a viewer", async () => {
    await mountPanel("p-1", false);
    expect(document.body.querySelector('[data-testid="person-rename-start"]')).toBeNull();
    expect(document.body.querySelector('[data-testid="delete-person"]')).toBeNull();
    expect(document.body.querySelector('[data-testid="delete-face-face-1"]')).toBeNull();
  });

  it("hides the enrollment panel for a viewer", async () => {
    await mountPanel("p-1", false);
    expect(document.body.querySelector('[data-testid="enroll-camera-select"]')).toBeNull();
  });

  it("shows the enrollment panel for an admin", async () => {
    await mountPanel();
    expect(document.body.querySelector('[data-testid="enroll-camera-select"]')).toBeTruthy();
  });
});

describe("PersonDetailPanel rename", () => {
  it("enters edit mode with the current name prefilled", async () => {
    mockedGetPerson.mockResolvedValue(makePerson({ name: "Alex" }));
    await mountPanel();
    document.body.querySelector<HTMLElement>('[data-testid="person-rename-start"]')?.click();
    await flushPromises();
    const input = document.body.querySelector<HTMLInputElement>('[data-testid="person-name-input"]');
    expect(input?.value).toBe("Alex");
  });

  it("cancels back to the display state", async () => {
    await mountPanel();
    document.body.querySelector<HTMLElement>('[data-testid="person-rename-start"]')?.click();
    await flushPromises();
    document.body.querySelector<HTMLElement>('[data-testid="person-name-cancel"]')?.click();
    await flushPromises();
    expect(document.body.querySelector('[data-testid="person-name-input"]')).toBeNull();
  });

  it("saves the new name", async () => {
    mockedUpdatePerson.mockResolvedValue(makePerson({ name: "Alexandra" }));
    await mountPanel();
    document.body.querySelector<HTMLElement>('[data-testid="person-rename-start"]')?.click();
    await flushPromises();
    const input = document.body.querySelector<HTMLInputElement>('[data-testid="person-name-input"]')!;
    input.value = "Alexandra";
    input.dispatchEvent(new Event("input"));
    document.body.querySelector<HTMLElement>('[data-testid="person-name-save"]')?.click();
    await flushPromises();
    expect(mockedUpdatePerson).toHaveBeenCalledWith("p-1", { name: "Alexandra" });
    expect(document.body.textContent).toContain("Alexandra");
  });

  it("does nothing when saving a blank name", async () => {
    await mountPanel();
    document.body.querySelector<HTMLElement>('[data-testid="person-rename-start"]')?.click();
    await flushPromises();
    const input = document.body.querySelector<HTMLInputElement>('[data-testid="person-name-input"]')!;
    input.value = "   ";
    input.dispatchEvent(new Event("input"));
    document.body.querySelector<HTMLElement>('[data-testid="person-name-save"]')?.click();
    await flushPromises();
    expect(mockedUpdatePerson).not.toHaveBeenCalled();
  });

  it("shows the API error message when renaming fails", async () => {
    mockedUpdatePerson.mockRejectedValue(new ApiError(400, "Name too long."));
    await mountPanel();
    document.body.querySelector<HTMLElement>('[data-testid="person-rename-start"]')?.click();
    await flushPromises();
    const input = document.body.querySelector<HTMLInputElement>('[data-testid="person-name-input"]')!;
    input.value = "Something";
    input.dispatchEvent(new Event("input"));
    document.body.querySelector<HTMLElement>('[data-testid="person-name-save"]')?.click();
    await flushPromises();
    expect(document.body.textContent).toContain("Name too long.");
  });

  it("falls back to a generic rename error for non-API failures", async () => {
    mockedUpdatePerson.mockRejectedValue(new TypeError("down"));
    await mountPanel();
    document.body.querySelector<HTMLElement>('[data-testid="person-rename-start"]')?.click();
    await flushPromises();
    const input = document.body.querySelector<HTMLInputElement>('[data-testid="person-name-input"]')!;
    input.value = "Something";
    input.dispatchEvent(new Event("input"));
    document.body.querySelector<HTMLElement>('[data-testid="person-name-save"]')?.click();
    await flushPromises();
    expect(document.body.textContent).toContain("Could not rename.");
  });
});

describe("PersonDetailPanel delete face", () => {
  it("asks for confirmation before deleting", async () => {
    await mountPanel();
    document.body.querySelector<HTMLElement>('[data-testid="delete-face-face-1"]')?.click();
    await flushPromises();
    const options = confirmRequire.mock.calls.at(-1)?.[0] as { header: string };
    expect(options.header).toBe("Delete face sample");
  });

  it("removes the face and decrements the count on confirm", async () => {
    mockedGetPerson.mockResolvedValue(makePerson({ face_count: 1 }));
    await mountPanel();
    document.body.querySelector<HTMLElement>('[data-testid="delete-face-face-1"]')?.click();
    await flushPromises();
    const options = confirmRequire.mock.calls.at(-1)?.[0] as { accept: () => void };
    options.accept();
    await flushPromises();

    expect(mockedDeleteFace).toHaveBeenCalledWith("p-1", "face-1");
    expect(document.body.querySelector('[data-testid="face-item-face-1"]')).toBeNull();
    expect(document.body.textContent).toContain("0 enrolled face sample(s)");
  });

  it("toasts the API error message when deleting a face fails", async () => {
    mockedDeleteFace.mockRejectedValue(new ApiError(404, "Face sample not found."));
    await mountPanel();
    document.body.querySelector<HTMLElement>('[data-testid="delete-face-face-1"]')?.click();
    await flushPromises();
    const options = confirmRequire.mock.calls.at(-1)?.[0] as { accept: () => void };
    options.accept();
    await flushPromises();
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "error", detail: "Face sample not found." }),
    );
  });

  it("toasts a generic error for a non-API face-delete failure", async () => {
    mockedDeleteFace.mockRejectedValue(new TypeError("down"));
    await mountPanel();
    document.body.querySelector<HTMLElement>('[data-testid="delete-face-face-1"]')?.click();
    await flushPromises();
    const options = confirmRequire.mock.calls.at(-1)?.[0] as { accept: () => void };
    options.accept();
    await flushPromises();
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "error", detail: "Unexpected error." }),
    );
  });
});

describe("PersonDetailPanel delete person", () => {
  it("asks for confirmation naming the person before deleting", async () => {
    mockedGetPerson.mockResolvedValue(makePerson({ name: "Alex" }));
    await mountPanel();
    document.body.querySelector<HTMLElement>('[data-testid="delete-person"]')?.click();
    await flushPromises();
    const options = confirmRequire.mock.calls.at(-1)?.[0] as { message: string };
    expect(options.message).toContain("Alex");
  });

  it("deletes and emits deleted on confirm", async () => {
    const wrapper = await mountPanel();
    document.body.querySelector<HTMLElement>('[data-testid="delete-person"]')?.click();
    await flushPromises();
    const options = confirmRequire.mock.calls.at(-1)?.[0] as { accept: () => void };
    options.accept();
    await flushPromises();

    expect(mockedDeletePerson).toHaveBeenCalledWith("p-1");
    expect(wrapper.emitted("deleted")).toHaveLength(1);
  });

  it("toasts the API error message when deleting the person fails", async () => {
    mockedDeletePerson.mockRejectedValue(new ApiError(409, "Cannot delete."));
    const wrapper = await mountPanel();
    document.body.querySelector<HTMLElement>('[data-testid="delete-person"]')?.click();
    await flushPromises();
    const options = confirmRequire.mock.calls.at(-1)?.[0] as { accept: () => void };
    options.accept();
    await flushPromises();
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "error", detail: "Cannot delete." }),
    );
    expect(wrapper.emitted("deleted")).toBeUndefined();
  });

  it("toasts a generic error for a non-API person-delete failure", async () => {
    mockedDeletePerson.mockRejectedValue(new TypeError("down"));
    await mountPanel();
    document.body.querySelector<HTMLElement>('[data-testid="delete-person"]')?.click();
    await flushPromises();
    const options = confirmRequire.mock.calls.at(-1)?.[0] as { accept: () => void };
    options.accept();
    await flushPromises();
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "error", detail: "Unexpected error." }),
    );
  });
});

describe("PersonDetailPanel enrollment integration", () => {
  it("refreshes the face grid when the embedded panel emits enrolled", async () => {
    mockedListFaces.mockResolvedValueOnce([makeFace({ id: "face-1" })]);
    const wrapper = await mountPanel();
    expect(document.body.querySelector('[data-testid="face-item-face-2"]')).toBeNull();

    mockedListFaces.mockResolvedValueOnce([
      makeFace({ id: "face-1" }),
      makeFace({ id: "face-2" }),
    ]);
    // The embedded PersonEnrollmentPanel's own wizard behavior is covered by
    // person-enrollment-panel.spec.ts - here we only prove PersonDetailPanel
    // reacts correctly to its "enrolled" event.
    await wrapper.findComponent({ name: "PersonEnrollmentPanel" }).vm.$emit("enrolled");
    await flushPromises();

    expect(mockedListFaces).toHaveBeenCalledTimes(2);
    expect(document.body.querySelector('[data-testid="face-item-face-2"]')).toBeTruthy();
    expect(document.body.textContent).toContain("2 enrolled face sample(s)");
  });
});
