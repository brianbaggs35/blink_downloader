import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/client";
import SettingsArchivedPanel from "@/components/SettingsArchivedPanel.vue";
import { makePinia, makeRouter, mountGlobal } from "./helpers";

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  getStorageIntegrationSettings: vi.fn(),
  updateStorageIntegrationSettings: vi.fn(),
}));

const toastAdd = vi.fn();
vi.mock("primevue/usetoast", () => ({
  useToast: () => ({ add: toastAdd }),
}));

import { getStorageIntegrationSettings, updateStorageIntegrationSettings } from "@/api";

const mockedGet = vi.mocked(getStorageIntegrationSettings);
const mockedUpdate = vi.mocked(updateStorageIntegrationSettings);

const baseSettings = {
  s3_enabled: false,
  s3_bucket: null,
  s3_region: null,
  s3_prefix: null,
  s3_credentials_set: false,
  google_drive_enabled: false,
  google_drive_client_id: null,
  google_drive_client_secret_set: false,
  google_drive_connected: false,
  google_drive_folder_id: null,
  onedrive_enabled: false,
  onedrive_client_id: null,
  onedrive_client_secret_set: false,
  onedrive_connected: false,
  onedrive_folder_path: null,
  auto_archive_backend: "local" as const,
};

beforeEach(() => {
  vi.clearAllMocks();
});

function mountPanel() {
  return mount(SettingsArchivedPanel, { global: mountGlobal(makePinia(), makeRouter()) });
}

describe("SettingsArchivedPanel loading", () => {
  it("shows a skeleton while loading", () => {
    mockedGet.mockReturnValue(new Promise(() => {}));
    const wrapper = mountPanel();
    expect(wrapper.find('[data-testid="archived-loading"]').exists()).toBe(true);
  });

  it("shows a load error on failure", async () => {
    mockedGet.mockRejectedValue(new ApiError(500, "boom"));
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find('[data-testid="archived-load-error"]').text()).toBe("boom");
  });

  it("falls back to a generic load error for non-API failures", async () => {
    mockedGet.mockRejectedValue(new TypeError("down"));
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find('[data-testid="archived-load-error"]').text()).toBe(
      "Could not load archival settings.",
    );
  });
});

describe("SettingsArchivedPanel destination select", () => {
  it("defaults the select to the current backend", async () => {
    mockedGet.mockResolvedValue({ ...baseSettings, auto_archive_backend: "s3" });
    const wrapper = mountPanel();
    await flushPromises();
    const select = wrapper.findComponent({ name: "Select" });
    expect(select.props("modelValue")).toBe("s3");
  });

  it("warns when the selected backend isn't connected yet", async () => {
    mockedGet.mockResolvedValue(baseSettings);
    const wrapper = mountPanel();
    await flushPromises();
    const select = wrapper.findComponent({ name: "Select" });
    await select.vm.$emit("update:modelValue", "google_drive");
    await flushPromises();
    expect(wrapper.find('[data-testid="archived-not-ready-warning"]').exists()).toBe(true);
  });

  it("warns when OneDrive is selected but not connected yet", async () => {
    mockedGet.mockResolvedValue(baseSettings);
    const wrapper = mountPanel();
    await flushPromises();
    const select = wrapper.findComponent({ name: "Select" });
    await select.vm.$emit("update:modelValue", "onedrive");
    await flushPromises();
    expect(wrapper.find('[data-testid="archived-not-ready-warning"]').exists()).toBe(true);
  });

  it("warns when OneDrive is enabled but its OAuth connection hasn't completed", async () => {
    mockedGet.mockResolvedValue({ ...baseSettings, onedrive_enabled: true });
    const wrapper = mountPanel();
    await flushPromises();
    const select = wrapper.findComponent({ name: "Select" });
    await select.vm.$emit("update:modelValue", "onedrive");
    await flushPromises();
    expect(wrapper.find('[data-testid="archived-not-ready-warning"]').exists()).toBe(true);
  });

  it("shows no warning once the selected backend is connected", async () => {
    mockedGet.mockResolvedValue({
      ...baseSettings,
      google_drive_enabled: true,
      google_drive_connected: true,
      auto_archive_backend: "google_drive",
    });
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find('[data-testid="archived-not-ready-warning"]').exists()).toBe(false);
  });

  it("shows no warning for the local destination", async () => {
    mockedGet.mockResolvedValue(baseSettings);
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find('[data-testid="archived-not-ready-warning"]').exists()).toBe(false);
  });

  it("links to the Integrations page from the warning", async () => {
    mockedGet.mockResolvedValue(baseSettings);
    const router = makeRouter();
    const pushSpy = vi.spyOn(router, "push");
    const wrapper = mount(SettingsArchivedPanel, { global: mountGlobal(makePinia(), router) });
    await flushPromises();
    const select = wrapper.findComponent({ name: "Select" });
    await select.vm.$emit("update:modelValue", "s3");
    await flushPromises();
    await wrapper.find('[data-testid="archived-go-to-integrations"]').trigger("click");
    expect(pushSpy).toHaveBeenCalledWith({ name: "integrations" });
  });
});

describe("SettingsArchivedPanel save", () => {
  it("saves the selected backend, preserving other provider fields", async () => {
    mockedGet.mockResolvedValue({
      ...baseSettings,
      s3_enabled: true,
      s3_bucket: "my-bucket",
      s3_region: "us-east-1",
      s3_prefix: "clips/",
      s3_credentials_set: true,
    });
    mockedUpdate.mockResolvedValue({
      ...baseSettings,
      s3_enabled: true,
      s3_bucket: "my-bucket",
      s3_credentials_set: true,
      auto_archive_backend: "s3",
    });
    const wrapper = mountPanel();
    await flushPromises();
    const select = wrapper.findComponent({ name: "Select" });
    await select.vm.$emit("update:modelValue", "s3");
    await wrapper.find('[data-testid="save-archived"]').trigger("click");
    await flushPromises();
    expect(mockedUpdate).toHaveBeenCalledWith(
      expect.objectContaining({
        s3_enabled: true,
        s3_bucket: "my-bucket",
        s3_region: "us-east-1",
        s3_prefix: "clips/",
        auto_archive_backend: "s3",
      }),
    );
    expect(toastAdd).toHaveBeenCalledWith(expect.objectContaining({ severity: "success" }));
  });

  it("shows an inline error on save failure", async () => {
    mockedGet.mockResolvedValue(baseSettings);
    mockedUpdate.mockRejectedValue(new ApiError(400, "nope"));
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="save-archived"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="archived-save-error"]').text()).toBe("nope");
  });

  it("falls back to a generic inline error for non-API save failures", async () => {
    mockedGet.mockResolvedValue(baseSettings);
    mockedUpdate.mockRejectedValue(new TypeError("down"));
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="save-archived"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="archived-save-error"]').text()).toBe("Unexpected error.");
  });
});
