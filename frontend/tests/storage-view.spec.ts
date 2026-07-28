import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import InputNumber from "primevue/inputnumber";
import Select from "primevue/select";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  getStorageSummary: vi.fn(),
  getStorageIntegrationSettings: vi.fn(),
  getStorageSettings: vi.fn(),
  updateStorageSettings: vi.fn(),
  updateStorageIntegrationSettings: vi.fn(),
  browseStorageDirectories: vi.fn(),
  createStorageDirectory: vi.fn(),
  browseCloudFolders: vi.fn(),
  createCloudFolder: vi.fn(),
}));

import {
  browseCloudFolders,
  browseStorageDirectories,
  getStorageIntegrationSettings,
  getStorageSettings,
  getStorageSummary,
  updateStorageIntegrationSettings,
  updateStorageSettings,
} from "@/api";
import { ApiError } from "@/api/client";
import { useAuthStore } from "@/stores/auth";
import StorageView from "@/views/StorageView.vue";
import { fakeStorageIntegrationSettings, fakeUser, makePinia, makeRouter, mountGlobal } from "./helpers";

import type { StorageIntegrationSettingsRead, StorageSettingsRead, StorageSummaryResponse } from "@/api";

const mockedSummary = vi.mocked(getStorageSummary);
const mockedIntegrationSettings = vi.mocked(getStorageIntegrationSettings);
const mockedStorageSettings = vi.mocked(getStorageSettings);
const mockedUpdateStorageSettings = vi.mocked(updateStorageSettings);
const mockedUpdateIntegrationSettings = vi.mocked(updateStorageIntegrationSettings);
const mockedBrowseStorage = vi.mocked(browseStorageDirectories);
const mockedBrowseCloud = vi.mocked(browseCloudFolders);

function summary(overrides: Partial<StorageSummaryResponse> = {}): StorageSummaryResponse {
  return {
    by_backend: [],
    total_clips: 0,
    total_bytes: 0,
    local_quota_bytes: null,
    ...overrides,
  };
}

function localSettings(overrides: Partial<StorageSettingsRead> = {}): StorageSettingsRead {
  return {
    storage_dir: "/data/clips",
    is_default: true,
    local_storage_quota_bytes: null,
    ...overrides,
  };
}

async function mountView(isAdmin = true) {
  const pinia = makePinia();
  useAuthStore().user = { ...fakeUser, is_superuser: isAdmin };
  const wrapper = mount(StorageView, { global: mountGlobal(pinia, makeRouter()) });
  await flushPromises();
  return wrapper;
}

function byTestId<T>(wrapper: VueWrapper, component: new () => T, testid: string): VueWrapper<T> {
  return wrapper
    .findAllComponents(component as never)
    .find((c) => c.attributes("data-testid") === testid) as unknown as VueWrapper<T>;
}

beforeEach(() => {
  vi.clearAllMocks();
  mockedIntegrationSettings.mockResolvedValue(fakeStorageIntegrationSettings());
  mockedStorageSettings.mockResolvedValue(localSettings());
});

describe("StorageView loading", () => {
  it("shows a loading skeleton while fetching", () => {
    mockedSummary.mockReturnValue(new Promise(() => {}));
    const wrapper = mount(StorageView, { global: mountGlobal(makePinia(), makeRouter()) });
    expect(wrapper.find('[data-testid="storage-loading"]').exists()).toBe(true);
  });

  it("shows a load error on failure", async () => {
    mockedSummary.mockRejectedValue(new ApiError(500, "boom"));
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="storage-load-error"]').text()).toBe("boom");
  });

  it("falls back to a generic load error for non-API failures", async () => {
    mockedSummary.mockRejectedValue(new TypeError("down"));
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="storage-load-error"]').text()).toBe(
      "Could not load storage usage.",
    );
  });

  it("refreshes on demand", async () => {
    mockedSummary.mockResolvedValue(summary());
    const wrapper = await mountView();
    await wrapper.find('[data-testid="refresh-storage"]').trigger("click");
    await flushPromises();
    expect(mockedSummary).toHaveBeenCalledTimes(2);
  });
});

describe("StorageView overview", () => {
  it("shows total clips and total size across all backends", async () => {
    mockedSummary.mockResolvedValue(summary({ total_clips: 7, total_bytes: 1024 * 1024 * 5 }));
    const wrapper = await mountView();
    expect(wrapper.text()).toContain("7");
    expect(wrapper.text()).toContain("5.0 MB");
  });
});

describe("StorageView per-backend cards", () => {
  it("shows clip count and size for each backend, defaulting to zero when absent", async () => {
    mockedSummary.mockResolvedValue(
      summary({
        by_backend: [{ backend: "s3", clip_count: 3, total_bytes: 2048 }],
        total_clips: 3,
        total_bytes: 2048,
      }),
    );
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="backend-card-s3"]').text()).toContain("3");
    expect(wrapper.find('[data-testid="backend-card-s3"]').text()).toContain("2.0 KB");
    expect(wrapper.find('[data-testid="backend-card-local"]').text()).toContain("0");
    expect(wrapper.find('[data-testid="backend-card-google_drive"]').text()).toContain("0");
    expect(wrapper.find('[data-testid="backend-card-onedrive"]').text()).toContain("0");
  });

  it("labels every backend card", async () => {
    mockedSummary.mockResolvedValue(summary());
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="backend-card-local"]').text()).toContain("Local disk");
    expect(wrapper.find('[data-testid="backend-card-s3"]').text()).toContain("Amazon S3");
    expect(wrapper.find('[data-testid="backend-card-google_drive"]').text()).toContain(
      "Google Drive",
    );
    expect(wrapper.find('[data-testid="backend-card-onedrive"]').text()).toContain(
      "Microsoft OneDrive",
    );
  });
});

describe("StorageView admin-only connection status", () => {
  it("shows connected/not-connected tags and a connect action for an admin", async () => {
    mockedSummary.mockResolvedValue(summary());
    mockedIntegrationSettings.mockResolvedValue(
      fakeStorageIntegrationSettings({ s3_enabled: true, s3_credentials_set: true }),
    );
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="backend-status-s3"]').text()).toBe("Connected");
    expect(wrapper.find('[data-testid="backend-status-google_drive"]').text()).toBe(
      "Not connected",
    );
    expect(wrapper.find('[data-testid="backend-connect-google_drive"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="backend-connect-s3"]').exists()).toBe(false);
  });

  it("treats an enabled-but-not-yet-authorized provider as not connected", async () => {
    mockedSummary.mockResolvedValue(summary());
    mockedIntegrationSettings.mockResolvedValue(
      fakeStorageIntegrationSettings({
        google_drive_enabled: true,
        google_drive_connected: false,
        onedrive_enabled: true,
        onedrive_connected: false,
      }),
    );
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="backend-status-google_drive"]').text()).toBe(
      "Not connected",
    );
    expect(wrapper.find('[data-testid="backend-status-onedrive"]').text()).toBe("Not connected");
  });

  it("does not request integration or storage settings, or show connection chrome, for a viewer", async () => {
    mockedSummary.mockResolvedValue(summary());
    const wrapper = await mountView(false);
    expect(mockedIntegrationSettings).not.toHaveBeenCalled();
    expect(mockedStorageSettings).not.toHaveBeenCalled();
    expect(wrapper.find('[data-testid="backend-status-s3"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="backend-connect-s3"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="auto-archive-summary"]').exists()).toBe(false);
  });
});

describe("StorageView connected-folder display", () => {
  it("shows the bucket and prefix for a connected S3 backend", async () => {
    mockedSummary.mockResolvedValue(summary());
    mockedIntegrationSettings.mockResolvedValue(
      fakeStorageIntegrationSettings({
        s3_enabled: true,
        s3_credentials_set: true,
        s3_bucket: "my-bucket",
        s3_prefix: "clips/",
      }),
    );
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="backend-folder-s3"]').text()).toBe("my-bucket/clips/");
  });

  it("shows just the bucket for S3 when there's no prefix", async () => {
    mockedSummary.mockResolvedValue(summary());
    mockedIntegrationSettings.mockResolvedValue(
      fakeStorageIntegrationSettings({
        s3_enabled: true,
        s3_credentials_set: true,
        s3_bucket: "my-bucket",
      }),
    );
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="backend-folder-s3"]').text()).toBe("my-bucket");
  });

  it("shows nothing for S3 when connected but no bucket is set", async () => {
    mockedSummary.mockResolvedValue(summary());
    mockedIntegrationSettings.mockResolvedValue(
      fakeStorageIntegrationSettings({ s3_enabled: true, s3_credentials_set: true }),
    );
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="backend-folder-s3"]').exists()).toBe(false);
  });

  it("shows the Drive folder id when set, and a root fallback otherwise", async () => {
    mockedSummary.mockResolvedValue(summary());
    mockedIntegrationSettings.mockResolvedValue(
      fakeStorageIntegrationSettings({
        google_drive_enabled: true,
        google_drive_connected: true,
        google_drive_folder_id: "drive-folder-1",
      }),
    );
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="backend-folder-google_drive"]').text()).toBe(
      "Folder ID: drive-folder-1",
    );
  });

  it("falls back to My Drive (root) when no Drive folder id is set", async () => {
    mockedSummary.mockResolvedValue(summary());
    mockedIntegrationSettings.mockResolvedValue(
      fakeStorageIntegrationSettings({ google_drive_enabled: true, google_drive_connected: true }),
    );
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="backend-folder-google_drive"]').text()).toBe(
      "My Drive (root)",
    );
  });

  it("shows the OneDrive folder path when set, and the BlinkClips default otherwise", async () => {
    mockedSummary.mockResolvedValue(summary());
    mockedIntegrationSettings.mockResolvedValue(
      fakeStorageIntegrationSettings({
        onedrive_enabled: true,
        onedrive_connected: true,
        onedrive_folder_path: "Custom/Path",
      }),
    );
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="backend-folder-onedrive"]').text()).toBe("Custom/Path");
  });

  it("falls back to BlinkClips when no OneDrive folder path is set", async () => {
    mockedSummary.mockResolvedValue(summary());
    mockedIntegrationSettings.mockResolvedValue(
      fakeStorageIntegrationSettings({ onedrive_enabled: true, onedrive_connected: true }),
    );
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="backend-folder-onedrive"]').text()).toBe("BlinkClips");
  });

  it("shows the current local storage folder for an admin", async () => {
    mockedSummary.mockResolvedValue(summary());
    mockedStorageSettings.mockResolvedValue(localSettings({ storage_dir: "/mnt/clips" }));
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="backend-folder-local"]').text()).toBe("/mnt/clips");
  });

  it("shows no local folder line for a viewer (no storage settings loaded)", async () => {
    mockedSummary.mockResolvedValue(summary());
    const wrapper = await mountView(false);
    expect(wrapper.find('[data-testid="backend-folder-local"]').exists()).toBe(false);
  });

  it("shows no folder line for a backend that isn't connected", async () => {
    mockedSummary.mockResolvedValue(summary());
    mockedIntegrationSettings.mockResolvedValue(
      fakeStorageIntegrationSettings({ s3_bucket: "my-bucket" }),
    );
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="backend-folder-s3"]').exists()).toBe(false);
  });

  it("shows no folder line for a viewer (no integrations detail loaded)", async () => {
    mockedSummary.mockResolvedValue(summary());
    const wrapper = await mountView(false);
    expect(wrapper.find('[data-testid="backend-folder-s3"]').exists()).toBe(false);
  });
});

describe("StorageView quota gauge", () => {
  it("shows an unset message and a 'Set a limit' action when no quota is set", async () => {
    mockedSummary.mockResolvedValue(
      summary({ by_backend: [{ backend: "local", clip_count: 1, total_bytes: 3072 }] }),
    );
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="storage-quota-gauge"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="storage-quota-unset"]').text()).toBe("No usage limit set.");
    expect(wrapper.find('[data-testid="edit-storage-quota"]').text()).toBe("Set a limit");
  });

  it("shows an 'Edit limit' action once a quota is set", async () => {
    mockedSummary.mockResolvedValue(
      summary({
        by_backend: [{ backend: "local", clip_count: 1, total_bytes: 3072 }],
        local_quota_bytes: 10240,
      }),
    );
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="edit-storage-quota"]').text()).toBe("Edit limit");
  });

  it("hides the quota edit action for a viewer, but still shows the unset message", async () => {
    mockedSummary.mockResolvedValue(
      summary({ by_backend: [{ backend: "local", clip_count: 1, total_bytes: 3072 }] }),
    );
    const wrapper = await mountView(false);
    expect(wrapper.find('[data-testid="storage-quota-unset"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="edit-storage-quota"]').exists()).toBe(false);
  });

  it("shows usage text and percent when a quota is set, colored green under the warning threshold", async () => {
    mockedSummary.mockResolvedValue(
      summary({
        by_backend: [{ backend: "local", clip_count: 1, total_bytes: 3072 }],
        local_quota_bytes: 10240,
      }),
    );
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="storage-quota-gauge"]').text()).toContain(
      "3.0 KB of 10.0 KB used",
    );
    expect(wrapper.find('[data-testid="storage-quota-percent"]').text()).toBe("30%");
    const meter = wrapper.findComponent({ name: "MeterGroup" });
    expect(meter.props("value")).toEqual([
      { label: "Used", value: 3072, color: "var(--p-green-500)" },
    ]);
    expect(meter.props("max")).toBe(10240);
  });

  it("colors the gauge yellow at the warning threshold", async () => {
    mockedSummary.mockResolvedValue(
      summary({
        by_backend: [{ backend: "local", clip_count: 1, total_bytes: 7680 }],
        local_quota_bytes: 10240,
      }),
    );
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="storage-quota-percent"]').text()).toBe("75%");
    expect(wrapper.findComponent({ name: "MeterGroup" }).props("value")).toEqual([
      { label: "Used", value: 7680, color: "var(--p-yellow-500)" },
    ]);
  });

  it("colors the gauge red at the critical threshold and caps the percent at 100", async () => {
    mockedSummary.mockResolvedValue(
      summary({
        by_backend: [{ backend: "local", clip_count: 1, total_bytes: 20480 }],
        local_quota_bytes: 10240,
      }),
    );
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="storage-quota-percent"]').text()).toBe("100%");
    expect(wrapper.findComponent({ name: "MeterGroup" }).props("value")).toEqual([
      { label: "Used", value: 20480, color: "var(--p-red-500)" },
    ]);
  });
});

describe("StorageView quota editing", () => {
  it("opens the form pre-filled with the current quota converted to GB", async () => {
    mockedSummary.mockResolvedValue(summary({ local_quota_bytes: 5 * 1024 ** 3 }));
    const wrapper = await mountView();
    await wrapper.find('[data-testid="edit-storage-quota"]').trigger("click");
    expect(byTestId(wrapper, InputNumber, "storage-quota-gb").props("modelValue")).toBe(5);
  });

  it("opens the form blank when no quota is set", async () => {
    mockedSummary.mockResolvedValue(summary());
    const wrapper = await mountView();
    await wrapper.find('[data-testid="edit-storage-quota"]').trigger("click");
    expect(byTestId(wrapper, InputNumber, "storage-quota-gb").props("modelValue")).toBeNull();
  });

  it("cancels editing without saving", async () => {
    mockedSummary.mockResolvedValue(summary());
    const wrapper = await mountView();
    await wrapper.find('[data-testid="edit-storage-quota"]').trigger("click");
    await wrapper.find('[data-testid="cancel-storage-quota"]').trigger("click");
    expect(wrapper.find('[data-testid="storage-quota-form"]').exists()).toBe(false);
    expect(mockedUpdateStorageSettings).not.toHaveBeenCalled();
  });

  it("saves the new quota and updates the gauge, echoing a null storage_dir while still on the default", async () => {
    mockedSummary.mockResolvedValue(
      summary({ by_backend: [{ backend: "local", clip_count: 1, total_bytes: 1024 ** 3 }] }),
    );
    mockedStorageSettings.mockResolvedValue(localSettings({ is_default: true }));
    mockedUpdateStorageSettings.mockResolvedValue(
      localSettings({ is_default: true, local_storage_quota_bytes: 10 * 1024 ** 3 }),
    );
    const wrapper = await mountView();
    await wrapper.find('[data-testid="edit-storage-quota"]').trigger("click");
    await byTestId(wrapper, InputNumber, "storage-quota-gb").vm.$emit("update:modelValue", 10);
    await wrapper.find('[data-testid="storage-quota-form"]').trigger("submit.prevent");
    await flushPromises();
    expect(mockedUpdateStorageSettings).toHaveBeenCalledWith({
      storage_dir: null,
      local_storage_quota_bytes: 10 * 1024 ** 3,
    });
    expect(wrapper.find('[data-testid="storage-quota-form"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="storage-quota-percent"]').text()).toBe("10%");
  });

  it("echoes the resolved storage_dir back unchanged when it's a custom override", async () => {
    mockedSummary.mockResolvedValue(summary());
    mockedStorageSettings.mockResolvedValue(
      localSettings({ storage_dir: "/mnt/custom", is_default: false }),
    );
    mockedUpdateStorageSettings.mockResolvedValue(
      localSettings({ storage_dir: "/mnt/custom", is_default: false }),
    );
    const wrapper = await mountView();
    await wrapper.find('[data-testid="edit-storage-quota"]').trigger("click");
    await wrapper.find('[data-testid="storage-quota-form"]').trigger("submit.prevent");
    await flushPromises();
    expect(mockedUpdateStorageSettings).toHaveBeenCalledWith(
      expect.objectContaining({ storage_dir: "/mnt/custom" }),
    );
  });

  it("sends a null quota when cleared", async () => {
    mockedSummary.mockResolvedValue(summary({ local_quota_bytes: 5 * 1024 ** 3 }));
    mockedUpdateStorageSettings.mockResolvedValue(localSettings());
    const wrapper = await mountView();
    await wrapper.find('[data-testid="edit-storage-quota"]').trigger("click");
    await byTestId(wrapper, InputNumber, "storage-quota-gb").vm.$emit("update:modelValue", null);
    await wrapper.find('[data-testid="storage-quota-form"]').trigger("submit.prevent");
    await flushPromises();
    expect(mockedUpdateStorageSettings).toHaveBeenCalledWith(
      expect.objectContaining({ local_storage_quota_bytes: null }),
    );
    expect(wrapper.find('[data-testid="storage-quota-unset"]').exists()).toBe(true);
  });

  it("shows an inline error with the API message when saving fails", async () => {
    mockedSummary.mockResolvedValue(summary());
    mockedUpdateStorageSettings.mockRejectedValue(new ApiError(400, "disk full"));
    const wrapper = await mountView();
    await wrapper.find('[data-testid="edit-storage-quota"]').trigger("click");
    await wrapper.find('[data-testid="storage-quota-form"]').trigger("submit.prevent");
    await flushPromises();
    expect(wrapper.find('[data-testid="storage-quota-error"]').text()).toBe("disk full");
  });

  it("falls back to a generic inline error for a non-API save failure", async () => {
    mockedSummary.mockResolvedValue(summary());
    mockedUpdateStorageSettings.mockRejectedValue(new TypeError("down"));
    const wrapper = await mountView();
    await wrapper.find('[data-testid="edit-storage-quota"]').trigger("click");
    await wrapper.find('[data-testid="storage-quota-form"]').trigger("submit.prevent");
    await flushPromises();
    expect(wrapper.find('[data-testid="storage-quota-error"]').text()).toBe(
      "Could not save the quota.",
    );
  });
});

describe("StorageView local folder browsing", () => {
  it("shows a Browse action for local disk but no Connect action", async () => {
    mockedSummary.mockResolvedValue(summary());
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="backend-browse-local"]').exists()).toBe(true);
  });

  it("hides the Browse action for a viewer", async () => {
    mockedSummary.mockResolvedValue(summary());
    const wrapper = await mountView(false);
    expect(wrapper.find('[data-testid="backend-browse-local"]').exists()).toBe(false);
  });

  it("selects a local folder and saves it immediately, echoing the current quota", async () => {
    mockedSummary.mockResolvedValue(summary({ local_quota_bytes: 500 }));
    mockedBrowseStorage.mockResolvedValue({ path: "/data/clips", parent_path: "/data", directories: [] });
    mockedUpdateStorageSettings.mockResolvedValue(
      localSettings({ storage_dir: "/data/clips/2026", local_storage_quota_bytes: 500 }),
    );
    const wrapper = await mountView();
    await wrapper.find('[data-testid="backend-browse-local"]').trigger("click");
    await flushPromises();
    (document.body.querySelector('[data-testid="storage-browse-select"]') as HTMLElement).click();
    await flushPromises();
    expect(mockedUpdateStorageSettings).toHaveBeenCalledWith({
      storage_dir: "/data/clips",
      local_storage_quota_bytes: 500,
    });
    expect(wrapper.find('[data-testid="backend-folder-local"]').text()).toBe("/data/clips/2026");
  });

  it("shows an inline error when saving the local folder fails", async () => {
    mockedSummary.mockResolvedValue(summary());
    mockedBrowseStorage.mockResolvedValue({ path: "/data/clips", parent_path: "/data", directories: [] });
    mockedUpdateStorageSettings.mockRejectedValue(new ApiError(400, "not writable"));
    const wrapper = await mountView();
    await wrapper.find('[data-testid="backend-browse-local"]').trigger("click");
    await flushPromises();
    (document.body.querySelector('[data-testid="storage-browse-select"]') as HTMLElement).click();
    await flushPromises();
    expect(wrapper.find('[data-testid="backend-folder-error-local"]').text()).toBe("not writable");
  });

  it("falls back to a generic error for a non-API local folder save failure", async () => {
    mockedSummary.mockResolvedValue(summary());
    mockedBrowseStorage.mockResolvedValue({ path: "/data/clips", parent_path: "/data", directories: [] });
    mockedUpdateStorageSettings.mockRejectedValue(new TypeError("down"));
    const wrapper = await mountView();
    await wrapper.find('[data-testid="backend-browse-local"]').trigger("click");
    await flushPromises();
    (document.body.querySelector('[data-testid="storage-browse-select"]') as HTMLElement).click();
    await flushPromises();
    expect(wrapper.find('[data-testid="backend-folder-error-local"]').text()).toBe(
      "Could not update the storage folder.",
    );
  });
});

function connectedIntegrationSettings(
  overrides: Partial<StorageIntegrationSettingsRead> = {},
): StorageIntegrationSettingsRead {
  return fakeStorageIntegrationSettings({
    s3_enabled: true,
    s3_credentials_set: true,
    google_drive_enabled: true,
    google_drive_connected: true,
    onedrive_enabled: true,
    onedrive_connected: true,
    ...overrides,
  });
}

describe("StorageView cloud folder browsing", () => {
  it("shows Browse only for a connected cloud backend, Connect otherwise", async () => {
    mockedSummary.mockResolvedValue(summary());
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="backend-browse-s3"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="backend-connect-s3"]').exists()).toBe(true);

    mockedIntegrationSettings.mockResolvedValue(connectedIntegrationSettings());
    const connectedWrapper = await mountView();
    expect(connectedWrapper.find('[data-testid="backend-browse-s3"]').exists()).toBe(true);
    expect(connectedWrapper.find('[data-testid="backend-connect-s3"]').exists()).toBe(false);
  });

  it("selects an S3 folder and saves the prefix, preserving every other setting", async () => {
    mockedSummary.mockResolvedValue(summary());
    mockedIntegrationSettings.mockResolvedValue(
      connectedIntegrationSettings({
        google_drive_client_id: "existing-drive-client",
        auto_archive_backend: "google_drive",
        auto_archive_after_days: 5,
      }),
    );
    mockedBrowseCloud.mockResolvedValue({ folders: [{ id: "clips", name: "Clips" }] });
    mockedUpdateIntegrationSettings.mockResolvedValue(connectedIntegrationSettings());
    const wrapper = await mountView();
    await wrapper.find('[data-testid="backend-browse-s3"]').trigger("click");
    await flushPromises();
    (
      document.body.querySelector('[data-testid="cloud-browse-entry-Clips"]') as HTMLElement
    ).click();
    await flushPromises();
    (document.body.querySelector('[data-testid="cloud-browse-select"]') as HTMLElement).click();
    await flushPromises();
    expect(mockedUpdateIntegrationSettings).toHaveBeenCalledWith({
      s3_enabled: true,
      s3_bucket: null,
      s3_region: null,
      s3_prefix: "clips/",
      s3_access_key_id: null,
      s3_secret_access_key: null,
      google_drive_enabled: true,
      google_drive_client_id: "existing-drive-client",
      google_drive_client_secret: null,
      google_drive_folder_id: null,
      onedrive_enabled: true,
      onedrive_client_id: null,
      onedrive_client_secret: null,
      onedrive_folder_path: null,
      auto_archive_backend: "google_drive",
      auto_archive_after_days: 5,
    });
  });

  it("selects the S3 bucket root and saves a null prefix", async () => {
    mockedSummary.mockResolvedValue(summary());
    mockedIntegrationSettings.mockResolvedValue(connectedIntegrationSettings());
    mockedBrowseCloud.mockResolvedValue({ folders: [] });
    mockedUpdateIntegrationSettings.mockResolvedValue(connectedIntegrationSettings());
    const wrapper = await mountView();
    await wrapper.find('[data-testid="backend-browse-s3"]').trigger("click");
    await flushPromises();
    (document.body.querySelector('[data-testid="cloud-browse-select"]') as HTMLElement).click();
    await flushPromises();
    expect(mockedUpdateIntegrationSettings).toHaveBeenCalledWith(
      expect.objectContaining({ s3_prefix: null }),
    );
  });

  it("selects a Google Drive folder and saves the folder id directly", async () => {
    mockedSummary.mockResolvedValue(summary());
    mockedIntegrationSettings.mockResolvedValue(connectedIntegrationSettings());
    mockedBrowseCloud.mockResolvedValue({ folders: [{ id: "drive-folder-id-1", name: "Backups" }] });
    mockedUpdateIntegrationSettings.mockResolvedValue(connectedIntegrationSettings());
    const wrapper = await mountView();
    await wrapper.find('[data-testid="backend-browse-google_drive"]').trigger("click");
    await flushPromises();
    (
      document.body.querySelector('[data-testid="cloud-browse-entry-Backups"]') as HTMLElement
    ).click();
    await flushPromises();
    (document.body.querySelector('[data-testid="cloud-browse-select"]') as HTMLElement).click();
    await flushPromises();
    expect(mockedUpdateIntegrationSettings).toHaveBeenCalledWith(
      expect.objectContaining({ google_drive_folder_id: "drive-folder-id-1" }),
    );
  });

  it("falls back to null for a Google Drive root selection", async () => {
    mockedSummary.mockResolvedValue(summary());
    mockedIntegrationSettings.mockResolvedValue(connectedIntegrationSettings());
    mockedBrowseCloud.mockResolvedValue({ folders: [] });
    mockedUpdateIntegrationSettings.mockResolvedValue(connectedIntegrationSettings());
    const wrapper = await mountView();
    await wrapper.find('[data-testid="backend-browse-google_drive"]').trigger("click");
    await flushPromises();
    (document.body.querySelector('[data-testid="cloud-browse-select"]') as HTMLElement).click();
    await flushPromises();
    expect(mockedUpdateIntegrationSettings).toHaveBeenCalledWith(
      expect.objectContaining({ google_drive_folder_id: null }),
    );
  });

  it("selects a OneDrive folder and saves the composed breadcrumb path", async () => {
    mockedSummary.mockResolvedValue(summary());
    mockedIntegrationSettings.mockResolvedValue(connectedIntegrationSettings());
    mockedBrowseCloud.mockResolvedValueOnce({ folders: [{ id: "opaque-1", name: "BlinkClips" }] });
    mockedBrowseCloud.mockResolvedValueOnce({ folders: [{ id: "opaque-2", name: "2026" }] });
    mockedUpdateIntegrationSettings.mockResolvedValue(connectedIntegrationSettings());
    const wrapper = await mountView();
    await wrapper.find('[data-testid="backend-browse-onedrive"]').trigger("click");
    await flushPromises();
    (
      document.body.querySelector('[data-testid="cloud-browse-entry-BlinkClips"]') as HTMLElement
    ).click();
    await flushPromises();
    (document.body.querySelector('[data-testid="cloud-browse-entry-2026"]') as HTMLElement).click();
    await flushPromises();
    (document.body.querySelector('[data-testid="cloud-browse-select"]') as HTMLElement).click();
    await flushPromises();
    expect(mockedUpdateIntegrationSettings).toHaveBeenCalledWith(
      expect.objectContaining({ onedrive_folder_path: "BlinkClips/2026" }),
    );
  });

  it("falls back to null for a OneDrive root selection", async () => {
    mockedSummary.mockResolvedValue(summary());
    mockedIntegrationSettings.mockResolvedValue(connectedIntegrationSettings());
    mockedBrowseCloud.mockResolvedValue({ folders: [] });
    mockedUpdateIntegrationSettings.mockResolvedValue(connectedIntegrationSettings());
    const wrapper = await mountView();
    await wrapper.find('[data-testid="backend-browse-onedrive"]').trigger("click");
    await flushPromises();
    (document.body.querySelector('[data-testid="cloud-browse-select"]') as HTMLElement).click();
    await flushPromises();
    expect(mockedUpdateIntegrationSettings).toHaveBeenCalledWith(
      expect.objectContaining({ onedrive_folder_path: null }),
    );
  });

  it("shows an inline error under the right backend card when saving a cloud folder fails", async () => {
    mockedSummary.mockResolvedValue(summary());
    mockedIntegrationSettings.mockResolvedValue(connectedIntegrationSettings());
    mockedBrowseCloud.mockResolvedValue({ folders: [] });
    mockedUpdateIntegrationSettings.mockRejectedValue(new ApiError(400, "bucket is full"));
    const wrapper = await mountView();
    await wrapper.find('[data-testid="backend-browse-s3"]').trigger("click");
    await flushPromises();
    (document.body.querySelector('[data-testid="cloud-browse-select"]') as HTMLElement).click();
    await flushPromises();
    expect(wrapper.find('[data-testid="backend-folder-error-s3"]').text()).toBe("bucket is full");
    expect(wrapper.find('[data-testid="backend-folder-error-google_drive"]').exists()).toBe(false);
  });

  it("falls back to a generic error for a non-API cloud folder save failure", async () => {
    mockedSummary.mockResolvedValue(summary());
    mockedIntegrationSettings.mockResolvedValue(connectedIntegrationSettings());
    mockedBrowseCloud.mockResolvedValue({ folders: [] });
    mockedUpdateIntegrationSettings.mockRejectedValue(new TypeError("down"));
    const wrapper = await mountView();
    await wrapper.find('[data-testid="backend-browse-s3"]').trigger("click");
    await flushPromises();
    (document.body.querySelector('[data-testid="cloud-browse-select"]') as HTMLElement).click();
    await flushPromises();
    expect(wrapper.find('[data-testid="backend-folder-error-s3"]').text()).toBe(
      "Could not save this folder.",
    );
  });

  it("clears the previous provider's error once a different provider is opened", async () => {
    mockedSummary.mockResolvedValue(summary());
    mockedIntegrationSettings.mockResolvedValue(connectedIntegrationSettings());
    mockedBrowseCloud.mockResolvedValue({ folders: [] });
    mockedUpdateIntegrationSettings.mockRejectedValueOnce(new ApiError(400, "bucket is full"));
    const wrapper = await mountView();
    await wrapper.find('[data-testid="backend-browse-s3"]').trigger("click");
    await flushPromises();
    (document.body.querySelector('[data-testid="cloud-browse-select"]') as HTMLElement).click();
    await flushPromises();
    expect(wrapper.find('[data-testid="backend-folder-error-s3"]').exists()).toBe(true);

    mockedUpdateIntegrationSettings.mockResolvedValue(connectedIntegrationSettings());
    await wrapper.find('[data-testid="backend-browse-google_drive"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="backend-folder-error-s3"]').exists()).toBe(false);
  });
});

describe("StorageView auto-archive summary", () => {
  it("reports local disk as the default destination", async () => {
    mockedSummary.mockResolvedValue(summary());
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="auto-archive-summary"]').text()).toContain(
      "New downloads stay on local disk.",
    );
  });

  it("names the configured backend when auto-archive points at one", async () => {
    mockedSummary.mockResolvedValue(summary());
    mockedIntegrationSettings.mockResolvedValue(
      fakeStorageIntegrationSettings({
        s3_enabled: true,
        s3_credentials_set: true,
        auto_archive_backend: "s3",
      }),
    );
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="auto-archive-summary"]').text()).toContain(
      "New downloads auto-archive to Amazon S3.",
    );
  });
});

describe("StorageView auto-archive editing", () => {
  it("hides the Edit action for a viewer", async () => {
    mockedSummary.mockResolvedValue(summary());
    const wrapper = await mountView(false);
    expect(wrapper.find('[data-testid="edit-auto-archive"]').exists()).toBe(false);
  });

  it("opens the form pre-filled with the current backend and delay", async () => {
    mockedSummary.mockResolvedValue(summary());
    mockedIntegrationSettings.mockResolvedValue(
      fakeStorageIntegrationSettings({
        s3_enabled: true,
        s3_credentials_set: true,
        auto_archive_backend: "s3",
        auto_archive_after_days: 14,
      }),
    );
    const wrapper = await mountView();
    await wrapper.find('[data-testid="edit-auto-archive"]').trigger("click");
    expect(byTestId(wrapper, Select, "auto-archive-backend").props("modelValue")).toBe("s3");
    expect(byTestId(wrapper, InputNumber, "auto-archive-after-days").props("modelValue")).toBe(14);
  });

  it("only offers local when no provider is connected, with a hint to connect one", async () => {
    mockedSummary.mockResolvedValue(summary());
    const wrapper = await mountView();
    await wrapper.find('[data-testid="edit-auto-archive"]').trigger("click");
    expect(byTestId(wrapper, Select, "auto-archive-backend").props("options")).toEqual([
      { label: "Local disk", value: "local" },
    ]);
    expect(wrapper.find('[data-testid="storage-no-providers-connected"]').exists()).toBe(true);
  });

  it("offers every connected provider, and hides the connect-one hint", async () => {
    mockedSummary.mockResolvedValue(summary());
    mockedIntegrationSettings.mockResolvedValue(
      connectedIntegrationSettings({ s3_enabled: true, s3_credentials_set: true }),
    );
    const wrapper = await mountView();
    await wrapper.find('[data-testid="edit-auto-archive"]').trigger("click");
    expect(byTestId(wrapper, Select, "auto-archive-backend").props("options")).toEqual([
      { label: "Local disk", value: "local" },
      { label: "Amazon S3", value: "s3" },
      { label: "Google Drive", value: "google_drive" },
      { label: "Microsoft OneDrive", value: "onedrive" },
    ]);
    expect(wrapper.find('[data-testid="storage-no-providers-connected"]').exists()).toBe(false);
  });

  it("self-heals a destination that's since been disconnected back to Local", async () => {
    mockedSummary.mockResolvedValue(summary());
    mockedIntegrationSettings.mockResolvedValue(
      fakeStorageIntegrationSettings({ s3_credentials_set: false, auto_archive_backend: "s3" }),
    );
    const wrapper = await mountView();
    await wrapper.find('[data-testid="edit-auto-archive"]').trigger("click");
    expect(byTestId(wrapper, Select, "auto-archive-backend").props("modelValue")).toBe("local");
  });

  it("cancels editing without saving", async () => {
    mockedSummary.mockResolvedValue(summary());
    const wrapper = await mountView();
    await wrapper.find('[data-testid="edit-auto-archive"]').trigger("click");
    await wrapper.find('[data-testid="cancel-auto-archive"]').trigger("click");
    expect(wrapper.find('[data-testid="auto-archive-form"]').exists()).toBe(false);
    expect(mockedUpdateIntegrationSettings).not.toHaveBeenCalled();
  });

  it("saves the backend and delay, preserving every other setting", async () => {
    mockedSummary.mockResolvedValue(summary());
    mockedIntegrationSettings.mockResolvedValue(
      connectedIntegrationSettings({
        google_drive_client_id: "existing-drive-client",
        auto_archive_backend: "local",
        auto_archive_after_days: 0,
      }),
    );
    mockedUpdateIntegrationSettings.mockResolvedValue(
      connectedIntegrationSettings({ auto_archive_backend: "s3", auto_archive_after_days: 7 }),
    );
    const wrapper = await mountView();
    await wrapper.find('[data-testid="edit-auto-archive"]').trigger("click");
    await byTestId(wrapper, Select, "auto-archive-backend").vm.$emit("update:modelValue", "s3");
    await byTestId(wrapper, InputNumber, "auto-archive-after-days").vm.$emit("update:modelValue", 7);
    await wrapper.find('[data-testid="auto-archive-form"]').trigger("submit.prevent");
    await flushPromises();
    expect(mockedUpdateIntegrationSettings).toHaveBeenCalledWith(
      expect.objectContaining({
        google_drive_client_id: "existing-drive-client",
        auto_archive_backend: "s3",
        auto_archive_after_days: 7,
      }),
    );
    expect(wrapper.find('[data-testid="auto-archive-form"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="auto-archive-summary"]').text()).toContain(
      "New downloads auto-archive to Amazon S3.",
    );
  });

  it("shows an inline error with the API message when saving fails", async () => {
    mockedSummary.mockResolvedValue(summary());
    mockedUpdateIntegrationSettings.mockRejectedValue(new ApiError(400, "nope"));
    const wrapper = await mountView();
    await wrapper.find('[data-testid="edit-auto-archive"]').trigger("click");
    await wrapper.find('[data-testid="auto-archive-form"]').trigger("submit.prevent");
    await flushPromises();
    expect(wrapper.find('[data-testid="auto-archive-error"]').text()).toBe("nope");
  });

  it("falls back to a generic inline error for a non-API save failure", async () => {
    mockedSummary.mockResolvedValue(summary());
    mockedUpdateIntegrationSettings.mockRejectedValue(new TypeError("down"));
    const wrapper = await mountView();
    await wrapper.find('[data-testid="edit-auto-archive"]').trigger("click");
    await wrapper.find('[data-testid="auto-archive-form"]').trigger("submit.prevent");
    await flushPromises();
    expect(wrapper.find('[data-testid="auto-archive-error"]').text()).toBe(
      "Could not save the archive policy.",
    );
  });

  it("navigates to Integrations from the connect-one-provider hint", async () => {
    mockedSummary.mockResolvedValue(summary());
    const router = makeRouter();
    const pushSpy = vi.spyOn(router, "push");
    const pinia = makePinia();
    useAuthStore().user = { ...fakeUser, is_superuser: true };
    const wrapper = mount(StorageView, { global: mountGlobal(pinia, router) });
    await flushPromises();
    await wrapper.find('[data-testid="edit-auto-archive"]').trigger("click");
    await wrapper.find('[data-testid="storage-go-to-integrations"]').trigger("click");
    expect(pushSpy).toHaveBeenCalledWith({ name: "integrations" });
  });
});

describe("StorageView navigation", () => {
  it("navigates to Integrations from a backend's Connect action", async () => {
    mockedSummary.mockResolvedValue(summary());
    const pinia = makePinia();
    useAuthStore().user = { ...fakeUser, is_superuser: true };
    const router = makeRouter();
    const pushSpy = vi.spyOn(router, "push");
    const wrapper = mount(StorageView, { global: mountGlobal(pinia, router) });
    await flushPromises();
    await wrapper.find('[data-testid="backend-connect-s3"]').trigger("click");
    expect(pushSpy).toHaveBeenCalledWith({ name: "integrations" });
  });

  it("navigates to Library from the footer hint", async () => {
    mockedSummary.mockResolvedValue(summary());
    const router = makeRouter();
    const pushSpy = vi.spyOn(router, "push");
    const wrapper = mount(StorageView, { global: mountGlobal(makePinia(), router) });
    await flushPromises();
    await wrapper.find('[data-testid="storage-go-to-library"]').trigger("click");
    expect(pushSpy).toHaveBeenCalledWith({ name: "library" });
  });
});
