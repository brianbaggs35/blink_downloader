import { flushPromises, mount } from "@vue/test-utils";
import InputNumber from "primevue/inputnumber";
import Select from "primevue/select";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/client";
import SettingsStoragePanel from "@/components/SettingsStoragePanel.vue";
import { fakeStorageIntegrationSettings, makePinia, makeRouter, mountGlobal } from "./helpers";

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  getStorageSettings: vi.fn(),
  updateStorageSettings: vi.fn(),
  getStorageIntegrationSettings: vi.fn(),
  updateStorageIntegrationSettings: vi.fn(),
}));

const toastAdd = vi.fn();
vi.mock("primevue/usetoast", () => ({
  useToast: () => ({ add: toastAdd }),
}));

import {
  getStorageIntegrationSettings,
  getStorageSettings,
  updateStorageIntegrationSettings,
  updateStorageSettings,
} from "@/api";

const mockedGetLocal = vi.mocked(getStorageSettings);
const mockedUpdateLocal = vi.mocked(updateStorageSettings);
const mockedGetIntegrations = vi.mocked(getStorageIntegrationSettings);
const mockedUpdateIntegrations = vi.mocked(updateStorageIntegrationSettings);

beforeEach(() => {
  vi.clearAllMocks();
  mockedGetLocal.mockResolvedValue({
    storage_dir: "/data/clips",
    is_default: true,
    local_storage_quota_bytes: null,
  });
  mockedGetIntegrations.mockResolvedValue(fakeStorageIntegrationSettings());
});

async function mountPanel() {
  const router = makeRouter();
  await router.push("/settings?tab=storage");
  const wrapper = mount(SettingsStoragePanel, { global: mountGlobal(makePinia(), router) });
  await flushPromises();
  return { wrapper, router };
}

describe("SettingsStoragePanel loading", () => {
  it("shows a skeleton while loading", () => {
    mockedGetLocal.mockReturnValue(new Promise(() => {}));
    const wrapper = mount(SettingsStoragePanel, { global: mountGlobal(makePinia(), makeRouter()) });
    expect(wrapper.find('[data-testid="storage-settings-loading"]').exists()).toBe(true);
  });

  it("shows a load error with the API message", async () => {
    mockedGetLocal.mockRejectedValue(new ApiError(500, "db down"));
    const { wrapper } = await mountPanel();
    expect(wrapper.find('[data-testid="storage-settings-load-error"]').text()).toBe("db down");
  });

  it("falls back to a generic load error for non-API failures", async () => {
    mockedGetLocal.mockRejectedValue(new TypeError("network down"));
    const { wrapper } = await mountPanel();
    expect(wrapper.find('[data-testid="storage-settings-load-error"]').text()).toBe(
      "Could not load storage settings.",
    );
  });
});

describe("SettingsStoragePanel local disk", () => {
  it("shows the current local folder", async () => {
    mockedGetLocal.mockResolvedValue({
      storage_dir: "/mnt/clips",
      is_default: false,
      local_storage_quota_bytes: null,
    });
    const { wrapper } = await mountPanel();
    expect(wrapper.find('[data-testid="current-local-folder"]').text()).toBe("/mnt/clips");
  });

  it("shows the quota converted from bytes to GB", async () => {
    mockedGetLocal.mockResolvedValue({
      storage_dir: "/data/clips",
      is_default: true,
      local_storage_quota_bytes: 500 * 1024 ** 3,
    });
    const { wrapper } = await mountPanel();
    const quota = wrapper.findComponent({ name: "InputNumber" });
    expect(quota.props("modelValue")).toBe(500);
  });

  it("leaves the quota blank when unset", async () => {
    const { wrapper } = await mountPanel();
    const quotaInputs = wrapper.findAllComponents(InputNumber);
    expect(quotaInputs[0]!.props("modelValue")).toBeNull();
  });
});

describe("SettingsStoragePanel archive destination", () => {
  it("only offers local when no provider is connected", async () => {
    const { wrapper } = await mountPanel();
    const select = wrapper.findComponent(Select);
    expect(select.props("options")).toEqual([{ label: "Local disk (default)", value: "local" }]);
    expect(wrapper.find('[data-testid="storage-no-providers-connected"]').exists()).toBe(true);
  });

  it("offers a connected S3 destination", async () => {
    mockedGetIntegrations.mockResolvedValue(
      fakeStorageIntegrationSettings({ s3_enabled: true, s3_credentials_set: true }),
    );
    const { wrapper } = await mountPanel();
    const select = wrapper.findComponent(Select);
    expect(select.props("options")).toEqual([
      { label: "Local disk (default)", value: "local" },
      { label: "Amazon S3", value: "s3" },
    ]);
    expect(wrapper.find('[data-testid="storage-no-providers-connected"]').exists()).toBe(false);
  });

  it("offers a connected Google Drive destination", async () => {
    mockedGetIntegrations.mockResolvedValue(
      fakeStorageIntegrationSettings({ google_drive_enabled: true, google_drive_connected: true }),
    );
    const { wrapper } = await mountPanel();
    const select = wrapper.findComponent(Select);
    expect(select.props("options")).toContainEqual({
      label: "Google Drive",
      value: "google_drive",
    });
  });

  it("offers a connected OneDrive destination", async () => {
    mockedGetIntegrations.mockResolvedValue(
      fakeStorageIntegrationSettings({ onedrive_enabled: true, onedrive_connected: true }),
    );
    const { wrapper } = await mountPanel();
    const select = wrapper.findComponent(Select);
    expect(select.props("options")).toContainEqual({
      label: "Microsoft OneDrive",
      value: "onedrive",
    });
  });

  it("self-heals a destination that's since been disconnected back to Local", async () => {
    // auto_archive_backend still literally says "s3" in the DB, but its
    // credentials have since been cleared - the Select must not be left
    // bound to a value that isn't among its own options.
    mockedGetIntegrations.mockResolvedValue(
      fakeStorageIntegrationSettings({
        s3_credentials_set: false,
        auto_archive_backend: "s3",
      }),
    );
    const { wrapper } = await mountPanel();
    const select = wrapper.findComponent(Select);
    expect(select.props("modelValue")).toBe("local");
    expect(wrapper.find('[data-testid="storage-no-providers-connected"]').exists()).toBe(true);
  });

  it("does not offer an enabled-but-not-yet-connected provider", async () => {
    mockedGetIntegrations.mockResolvedValue(
      fakeStorageIntegrationSettings({ s3_enabled: true, s3_credentials_set: false }),
    );
    const { wrapper } = await mountPanel();
    const select = wrapper.findComponent(Select);
    expect(select.props("options")).toEqual([{ label: "Local disk (default)", value: "local" }]);
  });

  it("populates the delay field from auto_archive_after_days", async () => {
    mockedGetIntegrations.mockResolvedValue(
      fakeStorageIntegrationSettings({ auto_archive_after_days: 14 }),
    );
    const { wrapper } = await mountPanel();
    const numbers = wrapper.findAllComponents(InputNumber);
    expect(numbers[1]!.props("modelValue")).toBe(14);
  });
});

describe("SettingsStoragePanel save", () => {
  it("saves the backend, delay, and quota together", async () => {
    mockedGetIntegrations.mockResolvedValue(
      fakeStorageIntegrationSettings({ s3_enabled: true, s3_credentials_set: true }),
    );
    mockedUpdateIntegrations.mockResolvedValue(
      fakeStorageIntegrationSettings({
        s3_enabled: true,
        s3_credentials_set: true,
        auto_archive_backend: "s3",
        auto_archive_after_days: 7,
      }),
    );
    mockedUpdateLocal.mockResolvedValue({
      storage_dir: "/data/clips",
      is_default: true,
      local_storage_quota_bytes: 10 * 1024 ** 3,
    });
    const { wrapper } = await mountPanel();

    const select = wrapper.findComponent(Select);
    await select.vm.$emit("update:modelValue", "s3");
    const numbers = wrapper.findAllComponents(InputNumber);
    await numbers[1]!.vm.$emit("update:modelValue", 7);
    await numbers[0]!.vm.$emit("update:modelValue", 10);
    await flushPromises();

    await wrapper.find('[data-testid="save-storage-settings"]').trigger("click");
    await flushPromises();

    expect(mockedUpdateIntegrations).toHaveBeenCalledWith(
      expect.objectContaining({ auto_archive_backend: "s3", auto_archive_after_days: 7 }),
    );
    expect(mockedUpdateLocal).toHaveBeenCalledWith({
      storage_dir: null,
      local_storage_quota_bytes: 10 * 1024 ** 3,
    });
    expect(toastAdd).toHaveBeenCalledWith(expect.objectContaining({ severity: "success" }));
  });

  it("echoes the resolved storage_dir back unchanged when it's a custom override", async () => {
    mockedGetLocal.mockResolvedValue({
      storage_dir: "/mnt/custom",
      is_default: false,
      local_storage_quota_bytes: null,
    });
    mockedUpdateIntegrations.mockResolvedValue(fakeStorageIntegrationSettings());
    mockedUpdateLocal.mockResolvedValue({
      storage_dir: "/mnt/custom",
      is_default: false,
      local_storage_quota_bytes: null,
    });
    const { wrapper } = await mountPanel();
    await wrapper.find('[data-testid="save-storage-settings"]').trigger("click");
    await flushPromises();
    expect(mockedUpdateLocal).toHaveBeenCalledWith({
      storage_dir: "/mnt/custom",
      local_storage_quota_bytes: null,
    });
  });

  it("sends null quota when cleared", async () => {
    mockedGetLocal.mockResolvedValue({
      storage_dir: "/data/clips",
      is_default: true,
      local_storage_quota_bytes: 5 * 1024 ** 3,
    });
    mockedUpdateIntegrations.mockResolvedValue(fakeStorageIntegrationSettings());
    mockedUpdateLocal.mockResolvedValue({
      storage_dir: "/data/clips",
      is_default: true,
      local_storage_quota_bytes: null,
    });
    const { wrapper } = await mountPanel();
    const numbers = wrapper.findAllComponents(InputNumber);
    await numbers[0]!.vm.$emit("update:modelValue", null);
    await flushPromises();
    await wrapper.find('[data-testid="save-storage-settings"]').trigger("click");
    await flushPromises();
    expect(mockedUpdateLocal).toHaveBeenCalledWith({
      storage_dir: null,
      local_storage_quota_bytes: null,
    });
  });

  it("shows an inline error with the API message when saving fails", async () => {
    mockedUpdateIntegrations.mockRejectedValue(new ApiError(400, "nope"));
    const { wrapper } = await mountPanel();
    await wrapper.find('[data-testid="save-storage-settings"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="storage-settings-save-error"]').text()).toBe("nope");
  });

  it("falls back to a generic inline error for a non-API save failure", async () => {
    mockedUpdateIntegrations.mockRejectedValue(new TypeError("down"));
    const { wrapper } = await mountPanel();
    await wrapper.find('[data-testid="save-storage-settings"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="storage-settings-save-error"]').text()).toBe(
      "Unexpected error.",
    );
  });
});

describe("SettingsStoragePanel navigation", () => {
  it("navigates to the Storage tab", async () => {
    const { wrapper, router } = await mountPanel();
    const pushSpy = vi.spyOn(router, "push");
    await wrapper.find('[data-testid="storage-go-to-storage-tab"]').trigger("click");
    expect(pushSpy).toHaveBeenCalledWith({ name: "storage" });
  });

  it("navigates to Integrations from the connect-a-provider hint", async () => {
    const { wrapper, router } = await mountPanel();
    const pushSpy = vi.spyOn(router, "push");
    await wrapper.find('[data-testid="storage-go-to-integrations"]').trigger("click");
    expect(pushSpy).toHaveBeenCalledWith({ name: "integrations" });
  });
});
