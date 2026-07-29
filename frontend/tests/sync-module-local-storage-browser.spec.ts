import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  listSyncModuleLocalStorageItems: vi.fn(),
  listSyncModules: vi.fn(),
  refreshSyncModuleLocalStorage: vi.fn(),
  downloadSyncModuleLocalStorageItem: vi.fn(),
  deleteSyncModuleLocalStorageItem: vi.fn(),
}));

const toastAdd = vi.fn();
vi.mock("primevue/usetoast", () => ({ useToast: () => ({ add: toastAdd }) }));

const confirmRequire = vi.fn();
vi.mock("primevue/useconfirm", () => ({ useConfirm: () => ({ require: confirmRequire }) }));

import {
  deleteSyncModuleLocalStorageItem,
  downloadSyncModuleLocalStorageItem,
  listSyncModuleLocalStorageItems,
  listSyncModules,
  refreshSyncModuleLocalStorage,
} from "@/api";
import { ApiError } from "@/api/client";
import SyncModuleLocalStorageBrowser from "@/components/SyncModuleLocalStorageBrowser.vue";
import { fakeUser, makePinia, mountGlobal } from "./helpers";
import { useAuthStore } from "@/stores/auth";

const mockedItems = vi.mocked(listSyncModuleLocalStorageItems);
const mockedSyncModules = vi.mocked(listSyncModules);
const mockedRefresh = vi.mocked(refreshSyncModuleLocalStorage);
const mockedDownload = vi.mocked(downloadSyncModuleLocalStorageItem);
const mockedDelete = vi.mocked(deleteSyncModuleLocalStorageItem);

const SYNC_MODULE_ID = "ssssssss-1111-2222-3333-444455556666";

function syncModuleFixture(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: SYNC_MODULE_ID,
    network_id: "net-1",
    name: "Home",
    serial: "SN-0001",
    firmware_version: "2.14.28",
    is_physical_hub: true,
    armed: true,
    online: true,
    local_storage_compatible: true,
    local_storage_enabled: true,
    local_storage_active: true,
    local_storage_status: "idle" as const,
    local_storage_manifest_refreshed_at: "2026-07-29T01:00:00Z",
    local_storage_last_error: null,
    camera_count: 2,
    last_synced_at: "2026-07-29T01:00:00Z",
    ...overrides,
  };
}

const availableItem = {
  id: "iiiiiiii-1111-2222-3333-444455556666",
  camera_id: "cccccccc-1111-2222-3333-444455556666",
  camera_name: "Front Door",
  recorded_at: "2026-07-29T00:00:00Z",
  size_bytes: 1024 * 1024,
  present_on_device: true,
  status: "available" as const,
  downloaded_at: null,
  last_error: null,
};

const downloadedItem = {
  ...availableItem,
  id: "jjjjjjjj-1111-2222-3333-444455556666",
  camera_id: null,
  camera_name: "Unmatched Camera",
  status: "downloaded" as const,
  downloaded_at: "2026-07-29T00:01:00Z",
};

const errorItem = {
  ...availableItem,
  id: "kkkkkkkk-1111-2222-3333-444455556666",
  status: "error" as const,
  last_error: "Could not prepare this clip.",
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

function mountBrowser(isAdmin = true) {
  const pinia = makePinia();
  useAuthStore().user = { ...fakeUser, is_superuser: isAdmin };
  return mount(SyncModuleLocalStorageBrowser, {
    props: { syncModuleId: SYNC_MODULE_ID },
    global: mountGlobal(pinia),
  });
}

describe("SyncModuleLocalStorageBrowser loading", () => {
  it("shows a loading skeleton while fetching", () => {
    mockedItems.mockReturnValue(new Promise(() => {}));
    mockedSyncModules.mockReturnValue(new Promise(() => {}));
    const wrapper = mountBrowser();
    expect(wrapper.find('[data-testid="local-storage-loading"]').exists()).toBe(true);
  });

  it("shows the API error message when loading fails", async () => {
    mockedItems.mockRejectedValue(new ApiError(500, "Server exploded"));
    mockedSyncModules.mockResolvedValue([syncModuleFixture()]);
    const wrapper = mountBrowser();
    await flushPromises();
    expect(wrapper.find('[data-testid="local-storage-load-error"]').text()).toBe(
      "Server exploded",
    );
  });

  it("falls back to a generic load error for non-API failures", async () => {
    mockedItems.mockRejectedValue(new TypeError("down"));
    mockedSyncModules.mockResolvedValue([syncModuleFixture()]);
    const wrapper = mountBrowser();
    await flushPromises();
    expect(wrapper.find('[data-testid="local-storage-load-error"]').text()).toBe(
      "Could not load local storage.",
    );
  });

  it("shows an empty-table message when there are no items", async () => {
    mockedItems.mockResolvedValue([]);
    mockedSyncModules.mockResolvedValue([syncModuleFixture()]);
    const wrapper = mountBrowser();
    await flushPromises();
    expect(wrapper.text()).toContain("No files found yet");
  });
});

describe("SyncModuleLocalStorageBrowser status header", () => {
  it("shows the last-refreshed timestamp and status tag", async () => {
    mockedItems.mockResolvedValue([]);
    mockedSyncModules.mockResolvedValue([syncModuleFixture()]);
    const wrapper = mountBrowser();
    await flushPromises();
    expect(wrapper.find('[data-testid="local-storage-status"]').text()).toBe("Idle");
    expect(wrapper.text()).toContain("Last refreshed");
  });

  it("shows 'Never refreshed yet' when there's no timestamp", async () => {
    mockedItems.mockResolvedValue([]);
    mockedSyncModules.mockResolvedValue([
      syncModuleFixture({ local_storage_manifest_refreshed_at: null }),
    ]);
    const wrapper = mountBrowser();
    await flushPromises();
    expect(wrapper.text()).toContain("Never refreshed yet");
  });

  it("doesn't crash and shows no status tag if its own sync module has vanished", async () => {
    mockedItems.mockResolvedValue([]);
    mockedSyncModules.mockResolvedValue([]);
    const wrapper = mountBrowser();
    await flushPromises();
    expect(wrapper.find('[data-testid="local-storage-status"]').exists()).toBe(false);
  });

  it("surfaces the last error message when the manifest status is error", async () => {
    mockedItems.mockResolvedValue([]);
    mockedSyncModules.mockResolvedValue([
      syncModuleFixture({ local_storage_status: "error", local_storage_last_error: "Device busy." }),
    ]);
    const wrapper = mountBrowser();
    await flushPromises();
    expect(wrapper.find('[data-testid="local-storage-status-error"]').text()).toBe("Device busy.");
  });
});

describe("SyncModuleLocalStorageBrowser table rows", () => {
  it("shows a Downloading label and disables actions while a clip is downloading", async () => {
    const downloading = { ...availableItem, status: "downloading" as const };
    mockedItems.mockResolvedValue([downloading]);
    mockedSyncModules.mockResolvedValue([syncModuleFixture()]);
    const wrapper = mountBrowser();
    await flushPromises();
    expect(wrapper.find(`[data-testid="item-status-${downloading.id}"]`).text()).toBe(
      "Downloading",
    );
    expect(wrapper.text()).toContain("Downloading…");
  });

  it("renders camera, size, and status for each item, flagging an unmatched camera", async () => {
    mockedItems.mockResolvedValue([availableItem, downloadedItem, errorItem]);
    mockedSyncModules.mockResolvedValue([syncModuleFixture()]);
    const wrapper = mountBrowser();
    await flushPromises();

    expect(wrapper.text()).toContain("Front Door");
    expect(wrapper.text()).toContain("1.0 MB");
    expect(wrapper.text()).toContain("Unmatched Camera");
    expect(wrapper.text()).toContain("(unmatched)");
    expect(wrapper.find(`[data-testid="item-status-${errorItem.id}"]`).text()).toBe("Error");
    expect(wrapper.text()).toContain("Could not prepare this clip.");
  });

  it("hides the actions column for a non-admin", async () => {
    mockedItems.mockResolvedValue([availableItem]);
    mockedSyncModules.mockResolvedValue([syncModuleFixture()]);
    const wrapper = mountBrowser(false);
    await flushPromises();
    expect(wrapper.find('[data-testid="refresh-local-storage"]').exists()).toBe(false);
    expect(wrapper.find(`[data-testid="download-item-${availableItem.id}"]`).exists()).toBe(false);
  });
});

describe("SyncModuleLocalStorageBrowser refresh", () => {
  it("triggers a refresh and shows a toast", async () => {
    mockedItems.mockResolvedValue([]);
    mockedSyncModules.mockResolvedValue([syncModuleFixture()]);
    mockedRefresh.mockResolvedValue(undefined);
    const wrapper = mountBrowser();
    await flushPromises();

    await wrapper.find('[data-testid="refresh-local-storage"]').trigger("click");
    await flushPromises();

    expect(mockedRefresh).toHaveBeenCalledWith(SYNC_MODULE_ID);
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "success", summary: expect.stringContaining("Refreshing") }),
    );
  });

  it("toasts an error when triggering a refresh fails", async () => {
    mockedItems.mockResolvedValue([]);
    mockedSyncModules.mockResolvedValue([syncModuleFixture()]);
    mockedRefresh.mockRejectedValue(new ApiError(502, "Sync Module offline."));
    const wrapper = mountBrowser();
    await flushPromises();

    await wrapper.find('[data-testid="refresh-local-storage"]').trigger("click");
    await flushPromises();

    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "error", detail: "Sync Module offline." }),
    );
  });

  it("toasts a generic error for a non-API refresh failure", async () => {
    mockedItems.mockResolvedValue([]);
    mockedSyncModules.mockResolvedValue([syncModuleFixture()]);
    mockedRefresh.mockRejectedValue(new TypeError("down"));
    const wrapper = mountBrowser();
    await flushPromises();

    await wrapper.find('[data-testid="refresh-local-storage"]').trigger("click");
    await flushPromises();

    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "error", detail: "Unexpected error." }),
    );
  });

  it("polls while the manifest is refreshing, and stops once idle", async () => {
    mockedItems.mockResolvedValue([]);
    mockedSyncModules
      .mockResolvedValueOnce([syncModuleFixture({ local_storage_status: "refreshing" })])
      .mockResolvedValueOnce([syncModuleFixture({ local_storage_status: "refreshing" })])
      .mockResolvedValue([syncModuleFixture({ local_storage_status: "idle" })]);
    const wrapper = mountBrowser();
    await flushPromises();
    expect(wrapper.find('[data-testid="local-storage-status"]').text()).toBe("Refreshing");

    await vi.advanceTimersByTimeAsync(3000);
    expect(wrapper.find('[data-testid="local-storage-status"]').text()).toBe("Refreshing");

    await vi.advanceTimersByTimeAsync(3000);
    expect(wrapper.find('[data-testid="local-storage-status"]').text()).toBe("Idle");

    const callsBeforeMoreTime = mockedSyncModules.mock.calls.length;
    await vi.advanceTimersByTimeAsync(10_000);
    expect(mockedSyncModules.mock.calls.length).toBe(callsBeforeMoreTime);
  });

  it("stops polling once unmounted, so it never leaks a timer", async () => {
    mockedItems.mockResolvedValue([]);
    mockedSyncModules.mockResolvedValue([syncModuleFixture({ local_storage_status: "refreshing" })]);
    const wrapper = mountBrowser();
    await flushPromises();
    const callsBeforeUnmount = mockedSyncModules.mock.calls.length;

    wrapper.unmount();
    await vi.advanceTimersByTimeAsync(10_000);

    expect(mockedSyncModules.mock.calls.length).toBe(callsBeforeUnmount);
  });
});

describe("SyncModuleLocalStorageBrowser download", () => {
  it("queues a download and disables the row until it resolves", async () => {
    mockedItems.mockResolvedValueOnce([availableItem]).mockResolvedValue([
      { ...availableItem, status: "preparing" },
    ]);
    mockedSyncModules.mockResolvedValue([syncModuleFixture()]);
    mockedDownload.mockResolvedValue(undefined);
    const wrapper = mountBrowser();
    await flushPromises();

    await wrapper.find(`[data-testid="download-item-${availableItem.id}"]`).trigger("click");
    await flushPromises();

    expect(mockedDownload).toHaveBeenCalledWith(SYNC_MODULE_ID, availableItem.id);
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "success", summary: "Queued for download" }),
    );
  });

  it("toasts an error when queuing a download fails", async () => {
    mockedItems.mockResolvedValue([availableItem]);
    mockedSyncModules.mockResolvedValue([syncModuleFixture()]);
    mockedDownload.mockRejectedValue(new ApiError(404, "Item not found."));
    const wrapper = mountBrowser();
    await flushPromises();

    await wrapper.find(`[data-testid="download-item-${availableItem.id}"]`).trigger("click");
    await flushPromises();

    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "error", detail: "Item not found." }),
    );
  });

  it("toasts a generic error for a non-API download failure", async () => {
    mockedItems.mockResolvedValue([availableItem]);
    mockedSyncModules.mockResolvedValue([syncModuleFixture()]);
    mockedDownload.mockRejectedValue(new TypeError("down"));
    const wrapper = mountBrowser();
    await flushPromises();

    await wrapper.find(`[data-testid="download-item-${availableItem.id}"]`).trigger("click");
    await flushPromises();

    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "error", detail: "Unexpected error." }),
    );
  });

  it("offers a retry download action for an errored item", async () => {
    mockedItems.mockResolvedValue([errorItem]);
    mockedSyncModules.mockResolvedValue([syncModuleFixture()]);
    const wrapper = mountBrowser();
    await flushPromises();
    expect(wrapper.find(`[data-testid="download-item-${errorItem.id}"]`).exists()).toBe(true);
  });

  it("offers a download link once an item has downloaded", async () => {
    mockedItems.mockResolvedValue([downloadedItem]);
    mockedSyncModules.mockResolvedValue([syncModuleFixture()]);
    const wrapper = mountBrowser();
    await flushPromises();
    const link = wrapper.find(`[data-testid="open-item-${downloadedItem.id}"]`);
    expect(link.attributes("href")).toBe(
      `/api/sync-modules/${SYNC_MODULE_ID}/local-storage/items/${downloadedItem.id}/file`,
    );
  });
});

describe("SyncModuleLocalStorageBrowser delete", () => {
  it("asks for confirmation before deleting a downloaded item", async () => {
    mockedItems.mockResolvedValue([downloadedItem]);
    mockedSyncModules.mockResolvedValue([syncModuleFixture()]);
    const wrapper = mountBrowser();
    await flushPromises();

    await wrapper.find(`[data-testid="delete-item-${downloadedItem.id}"]`).trigger("click");
    expect(confirmRequire).toHaveBeenCalledWith(
      expect.objectContaining({ header: "Delete from Sync Module" }),
    );
    expect(mockedDelete).not.toHaveBeenCalled();
  });

  it("deletes on confirmation and the row disappears once the poll confirms it's gone", async () => {
    mockedItems.mockResolvedValueOnce([downloadedItem]).mockResolvedValue([]);
    mockedSyncModules.mockResolvedValue([syncModuleFixture()]);
    mockedDelete.mockResolvedValue(undefined);
    const wrapper = mountBrowser();
    await flushPromises();

    await wrapper.find(`[data-testid="delete-item-${downloadedItem.id}"]`).trigger("click");
    const options = confirmRequire.mock.calls.at(-1)?.[0] as { accept: () => void };
    options.accept();
    await flushPromises();

    expect(mockedDelete).toHaveBeenCalledWith(SYNC_MODULE_ID, downloadedItem.id);
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "success", summary: "Queued for deletion" }),
    );
    expect(wrapper.find(`[data-testid="delete-item-${downloadedItem.id}"]`).exists()).toBe(false);
  });

  it("toasts an error when queuing a deletion fails", async () => {
    mockedItems.mockResolvedValue([downloadedItem]);
    mockedSyncModules.mockResolvedValue([syncModuleFixture()]);
    mockedDelete.mockRejectedValue(new ApiError(502, "Could not delete."));
    const wrapper = mountBrowser();
    await flushPromises();

    await wrapper.find(`[data-testid="delete-item-${downloadedItem.id}"]`).trigger("click");
    const options = confirmRequire.mock.calls.at(-1)?.[0] as { accept: () => void };
    options.accept();
    await flushPromises();

    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "error", detail: "Could not delete." }),
    );
  });

  it("toasts a generic error for a non-API deletion failure", async () => {
    mockedItems.mockResolvedValue([downloadedItem]);
    mockedSyncModules.mockResolvedValue([syncModuleFixture()]);
    mockedDelete.mockRejectedValue(new TypeError("down"));
    const wrapper = mountBrowser();
    await flushPromises();

    await wrapper.find(`[data-testid="delete-item-${downloadedItem.id}"]`).trigger("click");
    const options = confirmRequire.mock.calls.at(-1)?.[0] as { accept: () => void };
    options.accept();
    await flushPromises();

    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "error", detail: "Unexpected error." }),
    );
  });
});
