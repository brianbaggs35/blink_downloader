import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  getStorageSummary: vi.fn(),
  getStorageIntegrationSettings: vi.fn(),
}));

import { getStorageIntegrationSettings, getStorageSummary } from "@/api";
import { ApiError } from "@/api/client";
import { useAuthStore } from "@/stores/auth";
import StorageView from "@/views/StorageView.vue";
import { fakeStorageIntegrationSettings, fakeUser, makePinia, makeRouter, mountGlobal } from "./helpers";

import type { StorageSummaryResponse } from "@/api";

const mockedSummary = vi.mocked(getStorageSummary);
const mockedIntegrationSettings = vi.mocked(getStorageIntegrationSettings);

function summary(overrides: Partial<StorageSummaryResponse> = {}): StorageSummaryResponse {
  return {
    by_backend: [],
    total_clips: 0,
    total_bytes: 0,
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

beforeEach(() => {
  vi.clearAllMocks();
  mockedIntegrationSettings.mockResolvedValue(fakeStorageIntegrationSettings());
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

  it("does not request integration settings or show connection chrome for a viewer", async () => {
    mockedSummary.mockResolvedValue(summary());
    const wrapper = await mountView(false);
    expect(mockedIntegrationSettings).not.toHaveBeenCalled();
    expect(wrapper.find('[data-testid="backend-status-s3"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="backend-connect-s3"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="auto-archive-summary"]').exists()).toBe(false);
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

describe("StorageView navigation", () => {
  it("navigates to Settings > Archived from the auto-archive summary", async () => {
    mockedSummary.mockResolvedValue(summary());
    const pinia = makePinia();
    useAuthStore().user = { ...fakeUser, is_superuser: true };
    const router = makeRouter();
    const pushSpy = vi.spyOn(router, "push");
    const wrapper = mount(StorageView, { global: mountGlobal(pinia, router) });
    await flushPromises();
    await wrapper.find('[data-testid="storage-go-to-archived"]').trigger("click");
    expect(pushSpy).toHaveBeenCalledWith({ name: "settings", query: { tab: "archived" } });
  });

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
