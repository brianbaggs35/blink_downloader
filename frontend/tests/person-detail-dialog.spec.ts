import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  getPerson: vi.fn(),
  listPersonFaces: vi.fn(),
  updatePerson: vi.fn(),
  deleteFace: vi.fn(),
  deletePerson: vi.fn(),
}));

const toastAdd = vi.fn();
vi.mock("primevue/usetoast", () => ({ useToast: () => ({ add: toastAdd }) }));

const confirmRequire = vi.fn();
vi.mock("primevue/useconfirm", () => ({ useConfirm: () => ({ require: confirmRequire }) }));

import {
  deleteFace,
  deletePerson,
  getPerson,
  listPersonFaces,
  updatePerson,
} from "@/api";
import { ApiError } from "@/api/client";
import PersonDetailDialog from "@/components/PersonDetailDialog.vue";
import { useAuthStore } from "@/stores/auth";
import { fakeUser, makePinia, mountGlobal } from "./helpers";

import type { FaceEmbeddingRead, PersonRead } from "@/api";

const mockedGetPerson = vi.mocked(getPerson);
const mockedListFaces = vi.mocked(listPersonFaces);
const mockedUpdatePerson = vi.mocked(updatePerson);
const mockedDeleteFace = vi.mocked(deleteFace);
const mockedDeletePerson = vi.mocked(deletePerson);

function makePerson(overrides: Partial<PersonRead> = {}): PersonRead {
  return {
    id: "p-1",
    name: "Alex",
    has_thumbnail: false,
    face_count: 0,
    created_at: "2026-07-25T00:00:00Z",
    updated_at: "2026-07-25T00:00:00Z",
    ...overrides,
  };
}

function makeFace(overrides: Partial<FaceEmbeddingRead> = {}): FaceEmbeddingRead {
  return {
    id: "face-1",
    source_clip_id: "clip-1",
    source_frame_seconds: 2.5,
    created_at: "2026-07-25T00:00:00Z",
    ...overrides,
  };
}

function mountDialog(personId: string | null, isAdmin = true) {
  const pinia = makePinia();
  useAuthStore().user = { ...fakeUser, is_superuser: isAdmin };
  return mount(PersonDetailDialog, {
    props: { personId },
    global: mountGlobal(pinia),
    attachTo: document.body,
  });
}

async function mountReady(personId = "p-1", isAdmin = true) {
  const wrapper = mountDialog(personId, isAdmin);
  await nextTick();
  await flushPromises();
  return wrapper;
}

/** Simulates the user confirming the most recently opened confirm() dialog. */
function acceptLastConfirm(): void {
  const options = confirmRequire.mock.calls.at(-1)?.[0] as { accept: () => void };
  options.accept();
}

beforeEach(() => {
  vi.clearAllMocks();
  mockedGetPerson.mockResolvedValue(makePerson());
  mockedListFaces.mockResolvedValue([]);
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("PersonDetailDialog visibility", () => {
  it("is not visible when personId is null", () => {
    const wrapper = mountDialog(null);
    expect(document.body.querySelector('[data-testid="person-detail-dialog"]')).toBeNull();
    wrapper.unmount();
  });

  it("emits close when the dialog reports it was dismissed", async () => {
    const wrapper = await mountReady();
    await wrapper.findComponent({ name: "Dialog" }).vm.$emit("update:visible", false);
    expect(wrapper.emitted("close")).toHaveLength(1);
  });

  it("does not emit close when the dialog's visible model turns true", async () => {
    const wrapper = await mountReady();
    await wrapper.findComponent({ name: "Dialog" }).vm.$emit("update:visible", true);
    expect(wrapper.emitted("close")).toBeUndefined();
  });
});

describe("PersonDetailDialog loading", () => {
  it("shows a loading skeleton while fetching", async () => {
    mockedGetPerson.mockReturnValue(new Promise(() => {}));
    mountDialog("p-1");
    await nextTick();
    expect(document.body.querySelector('[data-testid="person-detail-loading"]')).toBeTruthy();
  });

  it("shows the API error message when loading fails", async () => {
    mockedGetPerson.mockRejectedValue(new ApiError(500, "Server exploded"));
    await mountReady();
    expect(document.body.textContent).toContain("Server exploded");
  });

  it("falls back to a generic load error for non-API failures", async () => {
    mockedListFaces.mockRejectedValue(new TypeError("down"));
    await mountReady();
    expect(document.body.textContent).toContain("Could not load this person.");
  });

  it("reloads when personId changes to a different person", async () => {
    const wrapper = await mountReady("p-1");
    expect(mockedGetPerson).toHaveBeenCalledWith("p-1");

    mockedGetPerson.mockResolvedValue(makePerson({ id: "p-2", name: "Sam" }));
    await wrapper.setProps({ personId: "p-2" });
    await flushPromises();
    expect(mockedGetPerson).toHaveBeenCalledWith("p-2");
    expect(document.body.textContent).toContain("Sam");
  });
});

describe("PersonDetailDialog content", () => {
  it("shows the name and an empty state when there are no face samples", async () => {
    await mountReady();
    expect(document.body.textContent).toContain("Alex");
    expect(document.body.textContent).toContain("No face samples yet");
  });

  it("renders a face grid item per sample with a thumbnail and delete button", async () => {
    mockedListFaces.mockResolvedValue([makeFace({ id: "face-1" }), makeFace({ id: "face-2" })]);
    await mountReady();
    expect(document.body.querySelector('[data-testid="face-item-face-1"]')).toBeTruthy();
    expect(document.body.querySelector('[data-testid="face-item-face-2"]')).toBeTruthy();
    expect(
      document.body.querySelector<HTMLImageElement>('[data-testid="face-item-face-1"] img')?.src,
    ).toContain("/api/biometrics/people/p-1/faces/face-1/thumbnail");
  });

  it("hides delete-face buttons for a non-admin", async () => {
    mockedListFaces.mockResolvedValue([makeFace()]);
    await mountReady("p-1", false);
    expect(document.body.querySelector('[data-testid="delete-face-face-1"]')).toBeNull();
  });
});

describe("PersonDetailDialog rename", () => {
  it("is hidden for a non-admin", async () => {
    await mountReady("p-1", false);
    expect(document.body.querySelector('[data-testid="person-rename-start"]')).toBeNull();
  });

  it("edits and saves a new name", async () => {
    mockedUpdatePerson.mockResolvedValue(makePerson({ name: "Alexandra" }));
    await mountReady();

    document.body.querySelector<HTMLElement>('[data-testid="person-rename-start"]')?.click();
    await nextTick();
    const input = document.body.querySelector<HTMLInputElement>('[data-testid="person-name-input"]')!;
    input.value = "Alexandra";
    input.dispatchEvent(new Event("input"));
    await nextTick();
    document.body.querySelector<HTMLElement>('[data-testid="person-name-save"]')?.click();
    await flushPromises();

    expect(mockedUpdatePerson).toHaveBeenCalledWith("p-1", { name: "Alexandra" });
    expect(document.body.querySelector('[data-testid="person-name-input"]')).toBeNull();
    expect(document.body.textContent).toContain("Alexandra");
  });

  it("shows the API error message when renaming fails", async () => {
    mockedUpdatePerson.mockRejectedValue(new ApiError(400, "Name already taken."));
    await mountReady();
    document.body.querySelector<HTMLElement>('[data-testid="person-rename-start"]')?.click();
    await nextTick();
    const input = document.body.querySelector<HTMLInputElement>('[data-testid="person-name-input"]')!;
    input.value = "Alexandra";
    input.dispatchEvent(new Event("input"));
    await nextTick();
    document.body.querySelector<HTMLElement>('[data-testid="person-name-save"]')?.click();
    await flushPromises();
    expect(document.body.textContent).toContain("Name already taken.");
  });

  it("falls back to a generic error for non-API rename failures", async () => {
    mockedUpdatePerson.mockRejectedValue(new TypeError("down"));
    await mountReady();
    document.body.querySelector<HTMLElement>('[data-testid="person-rename-start"]')?.click();
    await nextTick();
    const input = document.body.querySelector<HTMLInputElement>('[data-testid="person-name-input"]')!;
    input.value = "Alexandra";
    input.dispatchEvent(new Event("input"));
    await nextTick();
    document.body.querySelector<HTMLElement>('[data-testid="person-name-save"]')?.click();
    await flushPromises();
    expect(document.body.textContent).toContain("Could not rename.");
  });

  it("does nothing when saved with a blank name", async () => {
    await mountReady();
    document.body.querySelector<HTMLElement>('[data-testid="person-rename-start"]')?.click();
    await nextTick();
    const input = document.body.querySelector<HTMLInputElement>('[data-testid="person-name-input"]')!;
    input.value = "   ";
    input.dispatchEvent(new Event("input"));
    await nextTick();
    document.body.querySelector<HTMLElement>('[data-testid="person-name-save"]')?.click();
    await flushPromises();
    expect(mockedUpdatePerson).not.toHaveBeenCalled();
  });

  it("cancels editing without saving", async () => {
    await mountReady();
    document.body.querySelector<HTMLElement>('[data-testid="person-rename-start"]')?.click();
    await nextTick();
    document.body.querySelector<HTMLElement>('[data-testid="person-name-cancel"]')?.click();
    await nextTick();
    expect(document.body.querySelector('[data-testid="person-name-input"]')).toBeNull();
    expect(mockedUpdatePerson).not.toHaveBeenCalled();
  });
});

describe("PersonDetailDialog delete face", () => {
  it("removes the sample and decrements the visible face count on success", async () => {
    mockedListFaces.mockResolvedValue([makeFace({ id: "face-1" })]);
    mockedGetPerson.mockResolvedValue(makePerson({ face_count: 1 }));
    mockedDeleteFace.mockResolvedValue(undefined);
    await mountReady();

    document.body.querySelector<HTMLElement>('[data-testid="delete-face-face-1"]')?.click();
    acceptLastConfirm();
    await flushPromises();

    expect(mockedDeleteFace).toHaveBeenCalledWith("p-1", "face-1");
    expect(document.body.querySelector('[data-testid="face-item-face-1"]')).toBeNull();
    expect(document.body.textContent).toContain("No face samples yet");
  });

  it("toasts an error when deleting a face sample fails", async () => {
    mockedListFaces.mockResolvedValue([makeFace({ id: "face-1" })]);
    mockedDeleteFace.mockRejectedValue(new ApiError(500, "Storage unavailable."));
    await mountReady();

    document.body.querySelector<HTMLElement>('[data-testid="delete-face-face-1"]')?.click();
    acceptLastConfirm();
    await flushPromises();

    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "error", detail: "Storage unavailable." }),
    );
    expect(document.body.querySelector('[data-testid="face-item-face-1"]')).toBeTruthy();
  });

  it("falls back to a generic error toast for non-API delete-face failures", async () => {
    mockedListFaces.mockResolvedValue([makeFace({ id: "face-1" })]);
    mockedDeleteFace.mockRejectedValue(new TypeError("down"));
    await mountReady();

    document.body.querySelector<HTMLElement>('[data-testid="delete-face-face-1"]')?.click();
    acceptLastConfirm();
    await flushPromises();

    expect(toastAdd).toHaveBeenCalledWith(expect.objectContaining({ detail: "Unexpected error." }));
  });
});

describe("PersonDetailDialog delete person / enroll more", () => {
  it("hides the footer entirely for a non-admin", async () => {
    await mountReady("p-1", false);
    expect(document.body.querySelector('[data-testid="delete-person"]')).toBeNull();
    expect(document.body.querySelector('[data-testid="enroll-more"]')).toBeNull();
  });

  it("deletes the person, emits deleted, and closes", async () => {
    mockedDeletePerson.mockResolvedValue(undefined);
    const wrapper = await mountReady();

    document.body.querySelector<HTMLElement>('[data-testid="delete-person"]')?.click();
    acceptLastConfirm();
    await flushPromises();

    expect(mockedDeletePerson).toHaveBeenCalledWith("p-1");
    expect(wrapper.emitted("deleted")).toHaveLength(1);
    expect(wrapper.emitted("close")).toHaveLength(1);
  });

  it("toasts an error when deleting the person fails and stays open", async () => {
    mockedDeletePerson.mockRejectedValue(new ApiError(500, "Cannot delete."));
    const wrapper = await mountReady();

    document.body.querySelector<HTMLElement>('[data-testid="delete-person"]')?.click();
    acceptLastConfirm();
    await flushPromises();

    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "error", detail: "Cannot delete." }),
    );
    expect(wrapper.emitted("deleted")).toBeUndefined();
  });

  it("falls back to a generic error toast for a non-API delete-person failure", async () => {
    mockedDeletePerson.mockRejectedValue(new TypeError("down"));
    await mountReady();
    document.body.querySelector<HTMLElement>('[data-testid="delete-person"]')?.click();
    acceptLastConfirm();
    await flushPromises();
    expect(toastAdd).toHaveBeenCalledWith(expect.objectContaining({ detail: "Unexpected error." }));
  });

  it("emits enroll-more when its button is clicked", async () => {
    const wrapper = await mountReady();
    document.body.querySelector<HTMLElement>('[data-testid="enroll-more"]')?.click();
    expect(wrapper.emitted("enroll-more")).toHaveLength(1);
  });
});
