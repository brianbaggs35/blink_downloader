import { flushPromises, mount } from "@vue/test-utils";
import Select from "primevue/select";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/client";
import { useAuthStore } from "@/stores/auth";
import SettingsView from "@/views/SettingsView.vue";
import { fakeUser, makePinia, mountGlobal } from "./helpers";

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  updateMe: vi.fn(),
  getBlinkStatus: vi.fn(),
  getStorageSettings: vi.fn(),
  updateStorageSettings: vi.fn(),
}));

const toastAdd = vi.fn();
vi.mock("primevue/usetoast", () => ({
  useToast: () => ({ add: toastAdd }),
}));

import { getBlinkStatus, getStorageSettings, updateMe, updateStorageSettings } from "@/api";

const mockedUpdate = vi.mocked(updateMe);
const mockedBlinkStatus = vi.mocked(getBlinkStatus);
const mockedGetStorage = vi.mocked(getStorageSettings);
const mockedUpdateStorage = vi.mocked(updateStorageSettings);

const unlinkedBlinkStatus = {
  linked: false,
  status: null,
  last_sync: null,
  last_error: null,
  camera_count: 0,
} as const;

beforeEach(() => {
  vi.clearAllMocks();
  mockedBlinkStatus.mockResolvedValue(unlinkedBlinkStatus);
  mockedGetStorage.mockResolvedValue({ storage_dir: "/data/clips", is_default: true });
});

function mountSettings(withUser = true) {
  const pinia = makePinia();
  if (withUser) {
    useAuthStore().user = { ...fakeUser, timezone: "America/New_York" };
  }
  return mount(SettingsView, { global: mountGlobal(pinia) });
}

describe("SettingsView profile", () => {
  it("populates fields from the signed-in user", async () => {
    const wrapper = mountSettings();
    await flushPromises();
    const input = wrapper.find('[data-testid="display-name"]').element as HTMLInputElement;
    expect(input.value).toBe("Brian Baggs");
  });

  it("leaves defaults when no user is loaded", async () => {
    const wrapper = mountSettings(false);
    await flushPromises();
    const input = wrapper.find('[data-testid="display-name"]').element as HTMLInputElement;
    expect(input.value).toBe("");
  });

  it("saves the profile and toasts success", async () => {
    mockedUpdate.mockResolvedValue({ ...fakeUser, display_name: "Brian" });
    const wrapper = mountSettings();
    await wrapper.find('[data-testid="display-name"]').setValue("Brian");
    const timezoneSelect = wrapper.findComponent(Select);
    timezoneSelect.vm.$emit("update:modelValue", "Europe/London");
    await flushPromises();
    await wrapper.find('[data-testid="save-profile"]').trigger("click");
    await flushPromises();
    expect(mockedUpdate).toHaveBeenCalledWith({
      display_name: "Brian",
      timezone: "Europe/London",
    });
    expect(toastAdd).toHaveBeenCalledWith(expect.objectContaining({ severity: "success" }));
  });

  it("toasts API failures with their message", async () => {
    mockedUpdate.mockRejectedValue(new ApiError(400, "nope"));
    const wrapper = mountSettings();
    await wrapper.find('[data-testid="save-profile"]').trigger("click");
    await flushPromises();
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "error", detail: "nope" }),
    );
  });

  it("toasts unexpected failures generically", async () => {
    mockedUpdate.mockRejectedValue(new TypeError("down"));
    const wrapper = mountSettings();
    await wrapper.find('[data-testid="save-profile"]').trigger("click");
    await flushPromises();
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "error", detail: "Unexpected error." }),
    );
  });
});

describe("SettingsView password", () => {
  it("rejects short passwords", async () => {
    const wrapper = mountSettings();
    await wrapper.find('[data-testid="new-password"] input').setValue("short");
    await wrapper.find('[data-testid="save-password"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="password-error"]').text()).toContain("at least 12");
    expect(mockedUpdate).not.toHaveBeenCalled();
  });

  it("rejects mismatches", async () => {
    const wrapper = mountSettings();
    await wrapper.find('[data-testid="new-password"] input').setValue("a-long-enough-password");
    await wrapper.find('[data-testid="confirm-password"] input').setValue("different-password!");
    await wrapper.find('[data-testid="save-password"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="password-error"]').text()).toBe("Passwords do not match.");
  });

  it("updates the password and clears the fields", async () => {
    mockedUpdate.mockResolvedValue(fakeUser);
    const wrapper = mountSettings();
    await wrapper.find('[data-testid="new-password"] input').setValue("a-long-enough-password");
    await wrapper.find('[data-testid="confirm-password"] input').setValue("a-long-enough-password");
    await wrapper.find('[data-testid="save-password"]').trigger("click");
    await flushPromises();
    expect(mockedUpdate).toHaveBeenCalledWith({ password: "a-long-enough-password" });
    expect(toastAdd).toHaveBeenCalledWith(expect.objectContaining({ summary: "Password updated" }));
    const input = wrapper.find('[data-testid="new-password"] input').element as HTMLInputElement;
    expect(input.value).toBe("");
  });

  it("shows API rejections inline", async () => {
    mockedUpdate.mockRejectedValue(new ApiError(400, "Password must not contain your email."));
    const wrapper = mountSettings();
    await wrapper.find('[data-testid="new-password"] input').setValue("admin@example.com-pw");
    await wrapper.find('[data-testid="confirm-password"] input').setValue("admin@example.com-pw");
    await wrapper.find('[data-testid="save-password"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="password-error"]').text()).toBe(
      "Password must not contain your email.",
    );
  });

  it("falls back to a generic inline error", async () => {
    mockedUpdate.mockRejectedValue(new TypeError("down"));
    const wrapper = mountSettings();
    await wrapper.find('[data-testid="new-password"] input').setValue("a-long-enough-password");
    await wrapper.find('[data-testid="confirm-password"] input').setValue("a-long-enough-password");
    await wrapper.find('[data-testid="save-password"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="password-error"]').text()).toBe("Unexpected error.");
  });
});

describe("SettingsView appearance", () => {
  it("switches the theme from the select button", async () => {
    document.documentElement.classList.add("blink-dark");
    const wrapper = mountSettings();
    const options = wrapper.findAll('[data-testid="theme-select"] .p-togglebutton');
    expect(options.length).toBe(2);
    await options[1]!.trigger("click");
    await flushPromises();
    expect(document.documentElement.classList.contains("blink-dark")).toBe(false);
  });
});

describe("SettingsView storage", () => {
  it("is hidden for a non-superuser", async () => {
    const pinia = makePinia();
    useAuthStore().user = { ...fakeUser, is_superuser: false, timezone: "UTC" };
    const wrapper = mount(SettingsView, { global: mountGlobal(pinia) });
    await flushPromises();
    expect(wrapper.find('[data-testid="storage-dir"]').exists()).toBe(false);
    expect(mockedGetStorage).not.toHaveBeenCalled();
  });

  it("loads and displays the current storage directory for a superuser", async () => {
    mockedGetStorage.mockResolvedValue({ storage_dir: "/mnt/clips", is_default: false });
    const wrapper = mountSettings();
    await flushPromises();
    const input = wrapper.find('[data-testid="storage-dir"]').element as HTMLInputElement;
    expect(input.value).toBe("/mnt/clips");
    expect(wrapper.text()).toContain("Custom location.");
  });

  it("leaves the field blank when loading the current directory fails", async () => {
    mockedGetStorage.mockRejectedValue(new TypeError("network down"));
    const wrapper = mountSettings();
    await flushPromises();
    const input = wrapper.find('[data-testid="storage-dir"]').element as HTMLInputElement;
    expect(input.value).toBe("");
  });

  it("saves the storage directory and toasts success", async () => {
    mockedUpdateStorage.mockResolvedValue({ storage_dir: "/mnt/new", is_default: false });
    const wrapper = mountSettings();
    await flushPromises();
    await wrapper.find('[data-testid="storage-dir"]').setValue("/mnt/new");
    await wrapper.find('[data-testid="save-storage"]').trigger("click");
    await flushPromises();

    expect(mockedUpdateStorage).toHaveBeenCalledWith({ storage_dir: "/mnt/new" });
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ summary: "Storage location saved" }),
    );
    const input = wrapper.find('[data-testid="storage-dir"]').element as HTMLInputElement;
    expect(input.value).toBe("/mnt/new");
  });

  it("sends null when clearing the directory back to the default", async () => {
    mockedUpdateStorage.mockResolvedValue({ storage_dir: "/data/clips", is_default: true });
    const wrapper = mountSettings();
    await flushPromises();
    await wrapper.find('[data-testid="storage-dir"]').setValue("");
    await wrapper.find('[data-testid="save-storage"]').trigger("click");
    await flushPromises();
    expect(mockedUpdateStorage).toHaveBeenCalledWith({ storage_dir: null });
  });

  it("shows an inline error with the API message when saving fails", async () => {
    mockedUpdateStorage.mockRejectedValue(new ApiError(400, "Path is not writable."));
    const wrapper = mountSettings();
    await flushPromises();
    await wrapper.find('[data-testid="save-storage"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="storage-error"]').text()).toBe("Path is not writable.");
  });

  it("falls back to a generic inline error when saving fails with a non-API error", async () => {
    mockedUpdateStorage.mockRejectedValue(new TypeError("down"));
    const wrapper = mountSettings();
    await flushPromises();
    await wrapper.find('[data-testid="save-storage"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="storage-error"]').text()).toBe("Unexpected error.");
  });
});
