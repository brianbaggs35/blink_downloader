import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  listSyncModules: vi.fn(),
}));

import { listSyncModules } from "@/api";
import { ApiError } from "@/api/client";
import SettingsSyncModulePanel from "@/components/SettingsSyncModulePanel.vue";
import { makePinia, mountGlobal } from "./helpers";

const mockedList = vi.mocked(listSyncModules);

const syncModuleA = {
  id: "ssssssss-1111-2222-3333-444455556666",
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
};

const syncModuleB = {
  ...syncModuleA,
  id: "tttttttt-1111-2222-3333-444455556666",
  name: "Garage",
  serial: null,
  firmware_version: null,
  online: false,
  local_storage_compatible: false,
  local_storage_enabled: false,
};

beforeEach(() => {
  vi.clearAllMocks();
});

function mountPanel() {
  return mount(SettingsSyncModulePanel, { global: mountGlobal(makePinia()) });
}

describe("SettingsSyncModulePanel", () => {
  it("shows a loading skeleton while fetching", () => {
    mockedList.mockReturnValue(new Promise(() => {}));
    const wrapper = mountPanel();
    expect(wrapper.find('[data-testid="settings-sync-modules-loading"]').exists()).toBe(true);
  });

  it("shows the API error message when loading fails", async () => {
    mockedList.mockRejectedValue(new ApiError(500, "Server exploded"));
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find('[data-testid="settings-sync-modules-error"]').text()).toBe(
      "Server exploded",
    );
  });

  it("falls back to a generic load error for non-API failures", async () => {
    mockedList.mockRejectedValue(new TypeError("down"));
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find('[data-testid="settings-sync-modules-error"]').text()).toBe(
      "Could not load Sync Modules.",
    );
  });

  it("shows an empty state when there are none", async () => {
    mockedList.mockResolvedValue([]);
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find('[data-testid="settings-sync-modules-empty"]').exists()).toBe(true);
  });

  it("renders identity fields for each sync module, read-only", async () => {
    mockedList.mockResolvedValue([syncModuleA, syncModuleB]);
    const wrapper = mountPanel();
    await flushPromises();

    const rowA = wrapper.find(`[data-testid="settings-sync-module-row-${syncModuleA.id}"]`);
    expect(rowA.text()).toContain("Home");
    expect(rowA.text()).toContain("Online");
    expect(rowA.text()).toContain("SN-0001");
    expect(rowA.text()).toContain("2.14.28");
    expect(rowA.text()).toContain("Enabled");

    const rowB = wrapper.find(`[data-testid="settings-sync-module-row-${syncModuleB.id}"]`);
    expect(rowB.text()).toContain("Garage");
    expect(rowB.text()).toContain("Offline");
    expect(rowB.text()).toContain("Not supported");
    // No serial/firmware set for this one - shown as an em dash, not blank.
    expect(rowB.text()).toContain("—");

    // Nothing interactive - this is a read-only identity card.
    expect(wrapper.find("button").exists()).toBe(false);
  });

  it("distinguishes compatible-but-disabled local storage from unsupported", async () => {
    const disabledOnly = { ...syncModuleA, local_storage_enabled: false };
    mockedList.mockResolvedValue([disabledOnly]);
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.text()).toContain("Supported, not enabled");
  });

  it("shows Yes/No for whether the network has a physical hub", async () => {
    const noHub = { ...syncModuleB, is_physical_hub: false };
    mockedList.mockResolvedValue([syncModuleA, noHub]);
    const wrapper = mountPanel();
    await flushPromises();
    const rowA = wrapper.find(`[data-testid="settings-sync-module-row-${syncModuleA.id}"]`);
    expect(rowA.text()).toContain("Yes");
    const rowNoHub = wrapper.find(`[data-testid="settings-sync-module-row-${noHub.id}"]`);
    expect(rowNoHub.text()).toContain("No");
  });
});
