import { describe, expect, it, vi } from "vitest";

import {
  armSyncModule,
  bulkSetCameraMotionDetection,
  deleteSyncModuleLocalStorageItem,
  downloadSyncModuleLocalStorageItem,
  listSyncModuleCameras,
  listSyncModuleLocalStorageItems,
  listSyncModules,
  refreshSyncModuleLocalStorage,
  setCameraMotionDetection,
  syncModuleLocalStorageItemFileUrl,
} from "@/api";
import { jsonResponse } from "./helpers";

function capture(response: Response) {
  const mock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", mock);
  return mock;
}

const SYNC_MODULE_ID = "ssssssss-1111-2222-3333-444455556666";
const CAMERA_ID = "cccccccc-1111-2222-3333-444455556666";
const ITEM_ID = "iiiiiiii-1111-2222-3333-444455556666";

describe("sync module endpoints", () => {
  it("listSyncModules GETs /sync-modules", async () => {
    const mock = capture(jsonResponse([]));
    await listSyncModules();
    expect(mock.mock.calls[0]?.[0]).toBe("/api/sync-modules");
  });

  it("listSyncModuleCameras GETs the sync module's cameras", async () => {
    const mock = capture(jsonResponse([]));
    await listSyncModuleCameras(SYNC_MODULE_ID);
    expect(mock.mock.calls[0]?.[0]).toBe(`/api/sync-modules/${SYNC_MODULE_ID}/cameras`);
  });

  it("armSyncModule POSTs the armed flag", async () => {
    const mock = capture(jsonResponse({ armed: true }));
    await armSyncModule(SYNC_MODULE_ID, true);
    expect(mock.mock.calls[0]?.[0]).toBe(`/api/sync-modules/${SYNC_MODULE_ID}/arm`);
    const init = mock.mock.calls[0]?.[1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ armed: true });
  });

  it("setCameraMotionDetection PATCHes the individual camera's motion flag", async () => {
    const mock = capture(jsonResponse({ motion_enabled: false }));
    await setCameraMotionDetection(SYNC_MODULE_ID, CAMERA_ID, false);
    expect(mock.mock.calls[0]?.[0]).toBe(
      `/api/sync-modules/${SYNC_MODULE_ID}/cameras/${CAMERA_ID}/motion`,
    );
    const init = mock.mock.calls[0]?.[1] as RequestInit;
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body as string)).toEqual({ enabled: false });
  });

  it("bulkSetCameraMotionDetection PATCHes the bulk motion endpoint", async () => {
    const mock = capture(jsonResponse({ succeeded: 2, failed: 0 }));
    await bulkSetCameraMotionDetection(SYNC_MODULE_ID, true);
    expect(mock.mock.calls[0]?.[0]).toBe(`/api/sync-modules/${SYNC_MODULE_ID}/cameras/motion`);
    const init = mock.mock.calls[0]?.[1] as RequestInit;
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body as string)).toEqual({ enabled: true });
  });

  it("listSyncModuleLocalStorageItems GETs the local storage item list", async () => {
    const mock = capture(jsonResponse([]));
    await listSyncModuleLocalStorageItems(SYNC_MODULE_ID);
    expect(mock.mock.calls[0]?.[0]).toBe(
      `/api/sync-modules/${SYNC_MODULE_ID}/local-storage/items`,
    );
  });

  it("refreshSyncModuleLocalStorage POSTs to the refresh endpoint", async () => {
    const mock = capture(jsonResponse(null, 202));
    await refreshSyncModuleLocalStorage(SYNC_MODULE_ID);
    expect(mock.mock.calls[0]?.[0]).toBe(
      `/api/sync-modules/${SYNC_MODULE_ID}/local-storage/refresh`,
    );
    expect((mock.mock.calls[0]?.[1] as RequestInit).method).toBe("POST");
  });

  it("downloadSyncModuleLocalStorageItem POSTs to the item's download endpoint", async () => {
    const mock = capture(jsonResponse(null, 202));
    await downloadSyncModuleLocalStorageItem(SYNC_MODULE_ID, ITEM_ID);
    expect(mock.mock.calls[0]?.[0]).toBe(
      `/api/sync-modules/${SYNC_MODULE_ID}/local-storage/items/${ITEM_ID}/download`,
    );
    expect((mock.mock.calls[0]?.[1] as RequestInit).method).toBe("POST");
  });

  it("deleteSyncModuleLocalStorageItem DELETEs the item", async () => {
    const mock = capture(jsonResponse(null, 202));
    await deleteSyncModuleLocalStorageItem(SYNC_MODULE_ID, ITEM_ID);
    expect(mock.mock.calls[0]?.[0]).toBe(
      `/api/sync-modules/${SYNC_MODULE_ID}/local-storage/items/${ITEM_ID}`,
    );
    expect((mock.mock.calls[0]?.[1] as RequestInit).method).toBe("DELETE");
  });

  it("syncModuleLocalStorageItemFileUrl builds the file URL without fetching", () => {
    expect(syncModuleLocalStorageItemFileUrl(SYNC_MODULE_ID, ITEM_ID)).toBe(
      `/api/sync-modules/${SYNC_MODULE_ID}/local-storage/items/${ITEM_ID}/file`,
    );
  });
});
