import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";

import { ApiError } from "@/api/client";
import SettingsUsersPanel from "@/components/SettingsUsersPanel.vue";
import { useAuthStore } from "@/stores/auth";
import { fakeUser, makePinia, mountGlobal } from "./helpers";

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  listUsers: vi.fn(),
  createUser: vi.fn(),
}));

const toastAdd = vi.fn();
vi.mock("primevue/usetoast", () => ({
  useToast: () => ({ add: toastAdd }),
}));

import { createUser, listUsers } from "@/api";

const mockedList = vi.mocked(listUsers);
const mockedCreate = vi.mocked(createUser);

const viewerUser = {
  ...fakeUser,
  id: "aaaaaaaa-1111-2222-3333-444455556666",
  email: "viewer@example.com",
  display_name: "",
  is_superuser: false,
};

const disabledUser = {
  ...fakeUser,
  id: "bbbbbbbb-1111-2222-3333-444455556666",
  email: "gone@example.com",
  display_name: "Departed",
  is_active: false,
  is_superuser: false,
};

beforeEach(() => {
  vi.clearAllMocks();
  document.body.innerHTML = "";
});

function mountPanel() {
  const pinia = makePinia();
  useAuthStore().user = { ...fakeUser };
  return mount(SettingsUsersPanel, { global: mountGlobal(pinia), attachTo: document.body });
}

describe("SettingsUsersPanel loading", () => {
  it("shows a loading skeleton while fetching", () => {
    mockedList.mockReturnValue(new Promise(() => {}));
    const wrapper = mountPanel();
    expect(wrapper.find('[data-testid="users-loading"]').exists()).toBe(true);
  });

  it("renders users once loaded, including role/status/self tags", async () => {
    mockedList.mockResolvedValue([fakeUser, viewerUser, disabledUser]);
    const wrapper = mountPanel();
    await flushPromises();

    const list = wrapper.find('[data-testid="user-list"]');
    expect(list.exists()).toBe(true);

    const adminRow = wrapper.find(`[data-testid="user-row-${fakeUser.id}"]`);
    expect(adminRow.text()).toContain("Brian Baggs");
    expect(adminRow.text()).toContain("Admin");
    expect(adminRow.text()).toContain("You");

    const viewerRow = wrapper.find(`[data-testid="user-row-${viewerUser.id}"]`);
    // Falls back to email when display_name is blank.
    expect(viewerRow.text()).toContain("viewer@example.com");
    expect(viewerRow.text()).toContain("Viewer");
    expect(viewerRow.text()).not.toContain("You");

    const disabledRow = wrapper.find(`[data-testid="user-row-${disabledUser.id}"]`);
    expect(disabledRow.text()).toContain("Disabled");
  });

  it("shows the API error message when loading fails", async () => {
    mockedList.mockRejectedValue(new ApiError(500, "Server exploded"));
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find('[data-testid="users-load-error"]').text()).toBe("Server exploded");
  });

  it("falls back to a generic load error for non-API failures", async () => {
    mockedList.mockRejectedValue(new TypeError("down"));
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find('[data-testid="users-load-error"]').text()).toBe("Could not load users.");
  });
});

describe("SettingsUsersPanel invite flow", () => {
  beforeEach(() => {
    mockedList.mockResolvedValue([fakeUser]);
  });

  function setField(testId: string, value: string): void {
    // InputText puts the testid on the <input> itself; Password wraps it in
    // a span, so the testid lands one level up — handle both.
    const root = document.body.querySelector<HTMLElement>(`[data-testid="${testId}"]`);
    const el = root instanceof HTMLInputElement ? root : root!.querySelector("input");
    el!.value = value;
    el!.dispatchEvent(new Event("input"));
  }

  async function openInvite(wrapper: ReturnType<typeof mountPanel>): Promise<void> {
    await wrapper.find('[data-testid="open-invite"]').trigger("click");
    await flushPromises();
    await nextTick();
  }

  async function submitInvite(): Promise<void> {
    document.body.querySelector<HTMLFormElement>('[data-testid="invite-form"]')!
      .dispatchEvent(new Event("submit", { cancelable: true }));
    await flushPromises();
    await nextTick();
  }

  it("closes when the dialog reports it was dismissed", async () => {
    const wrapper = mountPanel();
    await flushPromises();
    await openInvite(wrapper);
    expect(document.body.querySelector('[data-testid="invite-modal"]')).toBeTruthy();
    await wrapper.findComponent({ name: "Dialog" }).vm.$emit("update:visible", false);
    await flushPromises();
    expect(document.body.querySelector('[data-testid="invite-modal"]')).toBeFalsy();
  });

  it("opens the invite dialog with cleared fields", async () => {
    const wrapper = mountPanel();
    await flushPromises();
    await openInvite(wrapper);
    const emailInput = document.body.querySelector<HTMLInputElement>(
      '[data-testid="invite-email"]',
    );
    expect(emailInput!.value).toBe("");
  });

  it("rejects a too-short password before calling the API", async () => {
    const wrapper = mountPanel();
    await flushPromises();
    await openInvite(wrapper);
    setField("invite-email", "new@example.com");
    setField("invite-password", "short");
    await submitInvite();
    expect(document.body.querySelector('[data-testid="invite-error"]')?.textContent).toContain(
      "at least 12",
    );
    expect(mockedCreate).not.toHaveBeenCalled();
  });

  it("creates a viewer by default and appends it to the list", async () => {
    const created = { ...viewerUser, id: "cccccccc-1111-2222-3333-444455556666" };
    mockedCreate.mockResolvedValue(created);
    const wrapper = mountPanel();
    await flushPromises();
    await openInvite(wrapper);
    setField("invite-email", "new@example.com");
    setField("invite-display-name", "New Person");
    setField("invite-password", "a-fine-long-password");
    await submitInvite();

    expect(mockedCreate).toHaveBeenCalledWith({
      email: "new@example.com",
      password: "a-fine-long-password",
      display_name: "New Person",
      is_superuser: false,
      is_active: true,
      is_verified: true,
      timezone: "UTC",
    });
    expect(toastAdd).toHaveBeenCalledWith(expect.objectContaining({ severity: "success" }));
    expect(wrapper.find(`[data-testid="user-row-${created.id}"]`).exists()).toBe(true);
  });

  it("creates an admin when the role toggle is switched", async () => {
    mockedCreate.mockResolvedValue({ ...fakeUser, id: "dddddddd-1111-2222-3333-444455556666" });
    const wrapper = mountPanel();
    await flushPromises();
    await openInvite(wrapper);
    setField("invite-email", "admin2@example.com");
    setField("invite-password", "a-fine-long-password");
    const adminOption = document.body.querySelectorAll<HTMLElement>(
      '[data-testid="invite-role"] .p-togglebutton',
    )[0]!;
    adminOption.click();
    await flushPromises();
    await nextTick();
    await submitInvite();
    expect(mockedCreate).toHaveBeenCalledWith(expect.objectContaining({ is_superuser: true }));
  });

  it("shows the API error inline and keeps the dialog open", async () => {
    mockedCreate.mockRejectedValue(new ApiError(400, "A user with this email already exists."));
    const wrapper = mountPanel();
    await flushPromises();
    await openInvite(wrapper);
    setField("invite-email", "admin@example.com");
    setField("invite-password", "a-fine-long-password");
    await submitInvite();
    expect(document.body.querySelector('[data-testid="invite-error"]')?.textContent).toBe(
      "A user with this email already exists.",
    );
    expect(document.body.querySelector('[data-testid="invite-modal"]')).toBeTruthy();
  });

  it("falls back to a generic error for non-API invite failures", async () => {
    mockedCreate.mockRejectedValue(new TypeError("down"));
    const wrapper = mountPanel();
    await flushPromises();
    await openInvite(wrapper);
    setField("invite-email", "admin@example.com");
    setField("invite-password", "a-fine-long-password");
    await submitInvite();
    expect(document.body.querySelector('[data-testid="invite-error"]')?.textContent).toBe(
      "Unexpected error.",
    );
  });
});
