import { describe, expect, it, vi } from "vitest";

import {
  browseStorageDirectories,
  bulkDeleteClips,
  createStorageDirectory,
  deleteClip,
  deleteStorageDirectory,
  downloadClipsAsZip,
  getBlinkStatus,
  getBlinkSyncSettings,
  getCameraBatteryEvents,
  getClip,
  getStorageSettings,
  linkBlinkAccount,
  listCameras,
  listClips,
  renameStorageDirectory,
  triggerBlinkSync,
  unlinkBlinkAccount,
  updateBlinkSyncSettings,
  updateCamera,
  updateStorageSettings,
  verifyBlinkAccount,
  clipDownloadUrl,
  clipStreamUrl,
  clipThumbnailUrl,
  ApiError,
} from "@/api";
import { jsonResponse } from "./helpers";

function capture(response: Response) {
  const mock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", mock);
  return mock;
}

describe("blink account endpoints", () => {
  it("linkBlinkAccount posts credentials", async () => {
    const mock = capture(jsonResponse({ status: "linked", link_session_id: null }));
    await linkBlinkAccount("brian@example.com", "hunter2");
    expect(mock.mock.calls[0]?.[0]).toBe("/api/blink/link");
    const init = mock.mock.calls[0]?.[1] as RequestInit;
    expect(JSON.parse(init.body as string)).toEqual({
      username: "brian@example.com",
      password: "hunter2",
    });
  });

  it("verifyBlinkAccount posts the session id and code", async () => {
    const mock = capture(jsonResponse({ status: "linked", link_session_id: null }));
    await verifyBlinkAccount("sess-1", "123456");
    const init = mock.mock.calls[0]?.[1] as RequestInit;
    expect(JSON.parse(init.body as string)).toEqual({
      link_session_id: "sess-1",
      code: "123456",
    });
  });

  it("getBlinkStatus GETs /blink/status", async () => {
    const mock = capture(jsonResponse({ linked: false }));
    await getBlinkStatus();
    expect(mock.mock.calls[0]?.[0]).toBe("/api/blink/status");
  });

  it("triggerBlinkSync POSTs /blink/sync", async () => {
    const mock = capture(jsonResponse({ status: "sync_started" }, 202));
    await triggerBlinkSync();
    expect((mock.mock.calls[0]?.[1] as RequestInit).method).toBe("POST");
  });

  it("unlinkBlinkAccount DELETEs /blink/account", async () => {
    const mock = capture(new Response(null, { status: 204 }));
    await unlinkBlinkAccount();
    expect(mock.mock.calls[0]?.[0]).toBe("/api/blink/account");
    expect((mock.mock.calls[0]?.[1] as RequestInit).method).toBe("DELETE");
  });
});

describe("camera endpoints", () => {
  it("listCameras GETs /cameras", async () => {
    const mock = capture(jsonResponse([]));
    await listCameras();
    expect(mock.mock.calls[0]?.[0]).toBe("/api/cameras");
  });

  it("updateCamera PATCHes with the enabled flag", async () => {
    const mock = capture(jsonResponse({ id: "1", enabled: false }));
    await updateCamera("1", false);
    expect(mock.mock.calls[0]?.[0]).toBe("/api/cameras/1");
    const init = mock.mock.calls[0]?.[1] as RequestInit;
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body as string)).toEqual({ enabled: false, security_context: null });
  });

  it("updateCamera PATCHes with a security context", async () => {
    const mock = capture(jsonResponse({ id: "1", enabled: true }));
    await updateCamera("1", true, "Watches the driveway");
    const init = mock.mock.calls[0]?.[1] as RequestInit;
    expect(JSON.parse(init.body as string)).toEqual({
      enabled: true,
      security_context: "Watches the driveway",
    });
  });

  it("getCameraBatteryEvents GETs the camera's battery-events history", async () => {
    const mock = capture(jsonResponse([]));
    await getCameraBatteryEvents("1");
    expect(mock.mock.calls[0]?.[0]).toBe("/api/cameras/1/battery-events");
  });
});

describe("clip endpoints", () => {
  it("listClips with no params hits the bare path", async () => {
    const mock = capture(jsonResponse({ items: [], total: 0, page: 1, page_size: 24 }));
    await listClips();
    expect(mock.mock.calls[0]?.[0]).toBe("/api/clips");
  });

  it("listClips serializes provided filters and omits empty ones", async () => {
    const mock = capture(jsonResponse({ items: [], total: 0, page: 1, page_size: 24 }));
    await listClips({ camera_id: "cam-1", downloaded_only: true, page: 2 });
    const url = mock.mock.calls[0]?.[0] as string;
    expect(url).toContain("camera_id=cam-1");
    expect(url).toContain("downloaded_only=true");
    expect(url).toContain("page=2");
    expect(url).not.toContain("since=");
  });

  it("listClips omits keys explicitly set to undefined, as LibraryView's cleared filters do", async () => {
    const mock = capture(jsonResponse({ items: [], total: 0, page: 1, page_size: 24 }));
    await listClips({ camera_id: undefined, since: undefined, until: undefined, page: 1 });
    const url = mock.mock.calls[0]?.[0] as string;
    expect(url).toContain("page=1");
    expect(url).not.toContain("camera_id=");
    expect(url).not.toContain("since=");
    expect(url).not.toContain("until=");
  });

  it("getClip GETs by id", async () => {
    const mock = capture(jsonResponse({ id: "1" }));
    await getClip("1");
    expect(mock.mock.calls[0]?.[0]).toBe("/api/clips/1");
  });

  it("deleteClip DELETEs by id", async () => {
    const mock = capture(new Response(null, { status: 204 }));
    await deleteClip("1");
    expect((mock.mock.calls[0]?.[1] as RequestInit).method).toBe("DELETE");
  });

  it("bulkDeleteClips posts the id list", async () => {
    const mock = capture(jsonResponse({ succeeded: 2, failed: 0 }));
    await bulkDeleteClips(["a", "b"]);
    const init = mock.mock.calls[0]?.[1] as RequestInit;
    expect(JSON.parse(init.body as string)).toEqual({ clip_ids: ["a", "b"] });
  });

  it("builds direct media URLs for the player/thumbnail/download", () => {
    expect(clipStreamUrl("1")).toBe("/api/clips/1/stream");
    expect(clipThumbnailUrl("1")).toBe("/api/clips/1/thumbnail");
    expect(clipDownloadUrl("1")).toBe("/api/clips/1/download");
  });
});

describe("downloadClipsAsZip", () => {
  it("posts ids and triggers a browser download of the returned blob", async () => {
    const blob = new Blob(["zip-bytes"], { type: "application/zip" });
    const response = new Response(blob, {
      status: 200,
      headers: { "content-disposition": 'attachment; filename="clips-20260101.zip"' },
    });
    const mock = capture(response);

    const clickSpy = vi.fn();
    const originalCreateElement = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
      const el = originalCreateElement(tag);
      if (tag === "a") {
        el.click = clickSpy;
      }
      return el;
    });
    const createObjectURL = vi.fn().mockReturnValue("blob:fake-url");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });

    await downloadClipsAsZip(["a", "b"]);

    expect(mock.mock.calls[0]?.[0]).toBe("/api/clips/bulk-download");
    const init = mock.mock.calls[0]?.[1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ clip_ids: ["a", "b"] });
    expect(clickSpy).toHaveBeenCalledOnce();
    expect(createObjectURL).toHaveBeenCalledOnce();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:fake-url");
  });

  it("falls back to a generic filename when content-disposition is missing", async () => {
    const blob = new Blob(["zip-bytes"]);
    capture(new Response(blob, { status: 200 }));
    vi.stubGlobal("URL", { ...URL, createObjectURL: vi.fn(() => "blob:x"), revokeObjectURL: vi.fn() });
    const clickSpy = vi.fn();
    const originalCreateElement = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
      const el = originalCreateElement(tag);
      if (tag === "a") {
        el.click = clickSpy;
      }
      return el;
    });

    await downloadClipsAsZip(["a"]);
    expect(clickSpy).toHaveBeenCalledOnce();
  });

  it("throws ApiError with the JSON detail on failure", async () => {
    capture(jsonResponse({ detail: "None of the selected clips have been downloaded yet." }, 404));
    const error = await downloadClipsAsZip(["a"]).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(404);
    expect((error as ApiError).message).toBe(
      "None of the selected clips have been downloaded yet.",
    );
  });

  it("falls back to statusText when the failure body isn't JSON", async () => {
    capture(new Response("<html>", { status: 500, statusText: "Server Error" }));
    const error = await downloadClipsAsZip(["a"]).catch((e: unknown) => e);
    expect((error as ApiError).message).toBe("Server Error");
  });

  it("falls back to statusText when the JSON body has no detail field", async () => {
    capture(new Response(JSON.stringify({}), { status: 500, statusText: "Server Error" }));
    const error = await downloadClipsAsZip(["a"]).catch((e: unknown) => e);
    expect((error as ApiError).message).toBe("Server Error");
  });
});

describe("settings endpoints", () => {
  it("getStorageSettings GETs /settings/storage", async () => {
    const mock = capture(jsonResponse({ storage_dir: "/data/clips", is_default: true }));
    await getStorageSettings();
    expect(mock.mock.calls[0]?.[0]).toBe("/api/settings/storage");
  });

  it("updateStorageSettings PATCHes the new path", async () => {
    const mock = capture(jsonResponse({ storage_dir: "/mnt/clips", is_default: false }));
    await updateStorageSettings({ storage_dir: "/mnt/clips" });
    const init = mock.mock.calls[0]?.[1] as RequestInit;
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body as string)).toEqual({ storage_dir: "/mnt/clips" });
  });

  it("browseStorageDirectories GETs /settings/storage/browse with no query when path is omitted", async () => {
    const mock = capture(jsonResponse({ path: "/data/clips", parent_path: "/data", directories: [] }));
    await browseStorageDirectories();
    expect(mock.mock.calls[0]?.[0]).toBe("/api/settings/storage/browse");
  });

  it("browseStorageDirectories GETs with a path query string", async () => {
    const mock = capture(jsonResponse({ path: "/mnt", parent_path: "/", directories: [] }));
    await browseStorageDirectories("/mnt");
    expect(mock.mock.calls[0]?.[0]).toBe("/api/settings/storage/browse?path=%2Fmnt");
  });

  it("createStorageDirectory POSTs the parent path and name", async () => {
    const mock = capture(
      jsonResponse({ path: "/data/clips/new", parent_path: "/data/clips", directories: [] }),
    );
    await createStorageDirectory("/data/clips", "new");
    expect(mock.mock.calls[0]?.[0]).toBe("/api/settings/storage/browse");
    const init = mock.mock.calls[0]?.[1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ parent_path: "/data/clips", name: "new" });
  });

  it("renameStorageDirectory PATCHes the path and new name", async () => {
    const mock = capture(
      jsonResponse({ path: "/data/clips", parent_path: "/data", directories: [] }),
    );
    await renameStorageDirectory("/data/clips/old", "new");
    expect(mock.mock.calls[0]?.[0]).toBe("/api/settings/storage/browse");
    const init = mock.mock.calls[0]?.[1] as RequestInit;
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body as string)).toEqual({ path: "/data/clips/old", new_name: "new" });
  });

  it("deleteStorageDirectory DELETEs with a path query string", async () => {
    const mock = capture(jsonResponse({ path: "/data/clips", parent_path: "/data", directories: [] }));
    await deleteStorageDirectory("/data/clips/old");
    expect(mock.mock.calls[0]?.[0]).toBe("/api/settings/storage/browse?path=%2Fdata%2Fclips%2Fold");
    const init = mock.mock.calls[0]?.[1] as RequestInit;
    expect(init.method).toBe("DELETE");
  });

  it("getBlinkSyncSettings GETs /settings/blink-sync", async () => {
    const mock = capture(
      jsonResponse({
        sync_interval_seconds: 60,
        initial_sync_days: 3,
        auto_analyze_limit: 5,
        is_default: true,
      }),
    );
    await getBlinkSyncSettings();
    expect(mock.mock.calls[0]?.[0]).toBe("/api/settings/blink-sync");
  });

  it("updateBlinkSyncSettings PUTs the new values", async () => {
    const mock = capture(
      jsonResponse({
        sync_interval_seconds: 90,
        initial_sync_days: 5,
        auto_analyze_limit: 8,
        is_default: false,
      }),
    );
    await updateBlinkSyncSettings({
      sync_interval_seconds: 90,
      initial_sync_days: 5,
      auto_analyze_limit: 8,
    });
    const init = mock.mock.calls[0]?.[1] as RequestInit;
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body as string)).toEqual({
      sync_interval_seconds: 90,
      initial_sync_days: 5,
      auto_analyze_limit: 8,
    });
  });
});
