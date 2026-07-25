import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  listPeople: vi.fn(),
  createPerson: vi.fn(),
}));

const toastAdd = vi.fn();
vi.mock("primevue/usetoast", () => ({ useToast: () => ({ add: toastAdd }) }));

import { createPerson, listPeople } from "@/api";
import { ApiError } from "@/api/client";
import EnrollFaceDialog from "@/components/EnrollFaceDialog.vue";
import PersonDetailDialog from "@/components/PersonDetailDialog.vue";
import { useAuthStore } from "@/stores/auth";
import BiometricsView from "@/views/BiometricsView.vue";
import { fakeUser, makePinia, makeRouter, mountGlobal } from "./helpers";

import type { PersonRead } from "@/api";

const mockedList = vi.mocked(listPeople);
const mockedCreate = vi.mocked(createPerson);

function makePerson(overrides: Partial<PersonRead> = {}): PersonRead {
  return {
    id: "person-1",
    name: "Alex",
    has_thumbnail: false,
    face_count: 0,
    created_at: "2026-07-25T00:00:00Z",
    updated_at: "2026-07-25T00:00:00Z",
    ...overrides,
  };
}

async function mountView(isAdmin = true) {
  const router = makeRouter();
  await router.push("/");
  const pinia = makePinia();
  useAuthStore().user = { ...fakeUser, is_superuser: isAdmin };
  const wrapper = mount(BiometricsView, {
    global: {
      ...mountGlobal(pinia, router),
      stubs: { EnrollFaceDialog: true, PersonDetailDialog: true },
    },
    attachTo: document.body,
  });
  await nextTick();
  await flushPromises();
  return wrapper;
}

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("BiometricsView loading", () => {
  it("shows a loading skeleton while fetching", () => {
    mockedList.mockReturnValue(new Promise(() => {}));
    const wrapper = mount(BiometricsView, {
      global: {
        ...mountGlobal(makePinia(), makeRouter()),
        stubs: { EnrollFaceDialog: true, PersonDetailDialog: true },
      },
    });
    expect(wrapper.find('[data-testid="people-loading"]').exists()).toBe(true);
  });

  it("shows a load-error state when loading fails, with a working retry", async () => {
    mockedList.mockRejectedValueOnce(new ApiError(500, "Server exploded"));
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="people-load-error"]').exists()).toBe(true);

    mockedList.mockResolvedValueOnce([]);
    await wrapper.find('[data-testid="retry-people"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="people-load-error"]').exists()).toBe(false);
    expect(wrapper.text()).toContain("No one enrolled yet");
  });

  it("shows the same load-error state for non-API failures", async () => {
    mockedList.mockRejectedValueOnce(new TypeError("down"));
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="people-load-error"]').text()).toContain(
      "Couldn't load people",
    );
  });
});

describe("BiometricsView empty state", () => {
  it("shows an empty state with an add-person action for admins", async () => {
    mockedList.mockResolvedValue([]);
    const wrapper = await mountView();
    expect(wrapper.text()).toContain("No one enrolled yet");
    expect(wrapper.find('[data-testid="open-add-person-empty"]').exists()).toBe(true);
  });

  it("hides the add-person action from non-admins", async () => {
    mockedList.mockResolvedValue([]);
    const wrapper = await mountView(false);
    expect(wrapper.find('[data-testid="open-add-person-empty"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="open-add-person"]').exists()).toBe(false);
  });
});

describe("BiometricsView people grid", () => {
  it("renders a card per person with name and face count", async () => {
    mockedList.mockResolvedValue([
      makePerson({ id: "p-1", name: "Alex", face_count: 3 }),
      makePerson({ id: "p-2", name: "Sam", face_count: 0 }),
    ]);
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="person-card-p-1"]').text()).toContain("Alex");
    expect(wrapper.find('[data-testid="person-card-p-1"]').text()).toContain("3 face sample(s)");
    expect(wrapper.find('[data-testid="person-card-p-2"]').text()).toContain("0 face sample(s)");
  });

  it("shows a thumbnail image only when has_thumbnail is true", async () => {
    mockedList.mockResolvedValue([
      makePerson({ id: "p-1", has_thumbnail: true }),
      makePerson({ id: "p-2", has_thumbnail: false }),
    ]);
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="person-card-p-1"] img').exists()).toBe(true);
    expect(wrapper.find('[data-testid="person-card-p-2"] img').exists()).toBe(false);
    expect(wrapper.find('[data-testid="person-card-p-2"] .pi-user').exists()).toBe(true);
  });

  it("opens the detail dialog for a clicked person", async () => {
    mockedList.mockResolvedValue([makePerson({ id: "p-1" })]);
    const wrapper = await mountView();
    await wrapper.find('[data-testid="person-card-p-1"]').trigger("click");
    expect(wrapper.findComponent(PersonDetailDialog).props("personId")).toBe("p-1");
  });

  it("opens the enroll dialog directly from a card's Enroll button, without opening the detail dialog", async () => {
    mockedList.mockResolvedValue([makePerson({ id: "p-1", name: "Alex" })]);
    const wrapper = await mountView();
    await wrapper.find('[data-testid="enroll-for-p-1"]').trigger("click");

    const enrollDialog = wrapper.findComponent(EnrollFaceDialog);
    expect(enrollDialog.props("personId")).toBe("p-1");
    expect(enrollDialog.props("personName")).toBe("Alex");
    expect(wrapper.findComponent(PersonDetailDialog).props("personId")).toBeNull();
  });

  it("hides per-card Enroll buttons for non-admins", async () => {
    mockedList.mockResolvedValue([makePerson({ id: "p-1" })]);
    const wrapper = await mountView(false);
    expect(wrapper.find('[data-testid="enroll-for-p-1"]').exists()).toBe(false);
  });
});

// PrimeVue's Dialog teleports its content to document.body one tick after
// mount, so it's queried/driven via the real document rather than
// wrapper.find (which only sees the component's own subtree) — same
// convention as clip-detail-modal.spec.ts and settings-users-panel.spec.ts.
async function openAddPersonDialog(wrapper: Awaited<ReturnType<typeof mountView>>): Promise<void> {
  await wrapper.find('[data-testid="open-add-person"]').trigger("click");
  await nextTick();
}

function setNameInput(value: string): void {
  const input = document.body.querySelector<HTMLInputElement>('[data-testid="new-person-name"]')!;
  input.value = value;
  input.dispatchEvent(new Event("input"));
}

describe("BiometricsView add-person dialog", () => {
  beforeEach(() => {
    mockedList.mockResolvedValue([]);
  });

  it("opens via the header button and disables submit until a name is typed", async () => {
    const wrapper = await mountView();
    await openAddPersonDialog(wrapper);
    expect(document.body.querySelector('[data-testid="add-person-dialog"]')).toBeTruthy();
    const submit = document.body.querySelector<HTMLButtonElement>(
      '[data-testid="submit-new-person"]',
    );
    expect(submit?.disabled).toBe(true);
  });

  it("closes when the dialog reports it was dismissed", async () => {
    const wrapper = await mountView();
    await openAddPersonDialog(wrapper);
    await wrapper.findComponent({ name: "Dialog" }).vm.$emit("update:visible", false);
    await nextTick();
    expect(document.body.querySelector('[data-testid="add-person-dialog"]')).toBeNull();
  });

  it("creates the person, inserting them alphabetically, closes the dialog, and opens the enroll dialog for them", async () => {
    mockedList.mockResolvedValue([makePerson({ id: "p-existing", name: "Sam" })]);
    mockedCreate.mockResolvedValue(makePerson({ id: "p-new", name: "Jordan" }));
    const wrapper = await mountView();
    await openAddPersonDialog(wrapper);
    setNameInput("Jordan");
    await nextTick();
    document.body.querySelector<HTMLElement>('[data-testid="submit-new-person"]')?.click();
    await flushPromises();

    expect(mockedCreate).toHaveBeenCalledWith({ name: "Jordan" });
    expect(document.body.querySelector('[data-testid="add-person-dialog"]')).toBeNull();
    const cards = wrapper.findAll('[data-testid^="person-card-"]');
    expect(cards.map((c) => c.text())).toEqual([
      expect.stringContaining("Jordan"),
      expect.stringContaining("Sam"),
    ]);
    const enrollDialog = wrapper.findComponent(EnrollFaceDialog);
    expect(enrollDialog.props("personId")).toBe("p-new");
    expect(enrollDialog.props("personName")).toBe("Jordan");
  });

  it("shows the API error message when creation fails", async () => {
    mockedCreate.mockRejectedValue(new ApiError(400, "Name already taken."));
    const wrapper = await mountView();
    await openAddPersonDialog(wrapper);
    setNameInput("Jordan");
    await nextTick();
    document.body.querySelector<HTMLElement>('[data-testid="submit-new-person"]')?.click();
    await flushPromises();
    expect(document.body.textContent).toContain("Name already taken.");
  });

  it("falls back to a generic create error for non-API failures", async () => {
    mockedCreate.mockRejectedValue(new TypeError("down"));
    const wrapper = await mountView();
    await openAddPersonDialog(wrapper);
    setNameInput("Jordan");
    await nextTick();
    document.body.querySelector<HTMLElement>('[data-testid="submit-new-person"]')?.click();
    await flushPromises();
    expect(document.body.textContent).toContain("Could not create person.");
  });

  it("does nothing if submitted with a blank name", async () => {
    const wrapper = await mountView();
    await openAddPersonDialog(wrapper);
    document.body
      .querySelector<HTMLFormElement>('[data-testid="add-person-dialog"] form')
      ?.dispatchEvent(new Event("submit", { cancelable: true }));
    await flushPromises();
    expect(mockedCreate).not.toHaveBeenCalled();
  });
});

describe("BiometricsView child dialog events", () => {
  it("reloads and toasts when the enroll dialog reports a successful enrollment", async () => {
    mockedList.mockResolvedValue([makePerson({ id: "p-1" })]);
    const wrapper = await mountView();
    await wrapper.find('[data-testid="enroll-for-p-1"]').trigger("click");

    mockedList.mockResolvedValue([makePerson({ id: "p-1", face_count: 1 })]);
    await wrapper.findComponent(EnrollFaceDialog).vm.$emit("enrolled");
    await flushPromises();

    expect(toastAdd).toHaveBeenCalledWith(expect.objectContaining({ severity: "success" }));
    expect(mockedList).toHaveBeenCalledTimes(2);
  });

  it("closes the enroll dialog when it emits close", async () => {
    mockedList.mockResolvedValue([makePerson({ id: "p-1" })]);
    const wrapper = await mountView();
    await wrapper.find('[data-testid="enroll-for-p-1"]').trigger("click");
    await wrapper.findComponent(EnrollFaceDialog).vm.$emit("close");
    await flushPromises();
    expect(wrapper.findComponent(EnrollFaceDialog).props("personId")).toBeNull();
  });

  it("closes the detail dialog when it emits close", async () => {
    mockedList.mockResolvedValue([makePerson({ id: "p-1" })]);
    const wrapper = await mountView();
    await wrapper.find('[data-testid="person-card-p-1"]').trigger("click");
    await wrapper.findComponent(PersonDetailDialog).vm.$emit("close");
    await flushPromises();
    expect(wrapper.findComponent(PersonDetailDialog).props("personId")).toBeNull();
  });

  it("reloads and toasts when the detail dialog reports a deletion", async () => {
    mockedList.mockResolvedValue([makePerson({ id: "p-1" })]);
    const wrapper = await mountView();
    await wrapper.find('[data-testid="person-card-p-1"]').trigger("click");

    mockedList.mockResolvedValue([]);
    await wrapper.findComponent(PersonDetailDialog).vm.$emit("deleted");
    await flushPromises();

    expect(toastAdd).toHaveBeenCalledWith(expect.objectContaining({ severity: "success" }));
    expect(mockedList).toHaveBeenCalledTimes(2);
  });

  it("switches from the detail dialog to the enroll dialog for the same person on enroll-more", async () => {
    mockedList.mockResolvedValue([makePerson({ id: "p-1", name: "Alex" })]);
    const wrapper = await mountView();
    await wrapper.find('[data-testid="person-card-p-1"]').trigger("click");

    await wrapper.findComponent(PersonDetailDialog).vm.$emit("enroll-more");
    await flushPromises();

    expect(wrapper.findComponent(PersonDetailDialog).props("personId")).toBeNull();
    const enrollDialog = wrapper.findComponent(EnrollFaceDialog);
    expect(enrollDialog.props("personId")).toBe("p-1");
    expect(enrollDialog.props("personName")).toBe("Alex");
  });

  it("does nothing on enroll-more if the previously selected person can no longer be found", async () => {
    mockedList.mockResolvedValue([makePerson({ id: "p-1", name: "Alex" })]);
    const wrapper = await mountView();
    await wrapper.find('[data-testid="person-card-p-1"]').trigger("click");

    // Simulate the person having vanished from the loaded list.
    mockedList.mockResolvedValue([]);
    await wrapper.findComponent(PersonDetailDialog).vm.$emit("deleted");
    await flushPromises();
    await wrapper.findComponent(PersonDetailDialog).vm.$emit("enroll-more");
    await flushPromises();

    expect(wrapper.findComponent(EnrollFaceDialog).props("personId")).toBeNull();
  });
});
