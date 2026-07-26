import { describe, expect, it, vi } from "vitest";

import {
  cameraPreviewUrl,
  getLiveViewSettings,
  getSecurityFeedSettings,
  recordCameraClip,
  updateLiveViewSettings,
  updateSecurityFeedSettings,
} from "@/api";
import { jsonResponse } from "./helpers";

function capture(response: Response) {
  const mock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", mock);
  return mock;
}

describe("camera preview/record endpoints", () => {
  it("cameraPreviewUrl builds a passive, force-less URL by default", () => {
    expect(cameraPreviewUrl("cam-1")).toBe("/api/cameras/cam-1/preview");
  });

  it("cameraPreviewUrl appends force=true when requested", () => {
    expect(cameraPreviewUrl("cam-1", { force: true })).toBe(
      "/api/cameras/cam-1/preview?force=true",
    );
  });

  it("recordCameraClip POSTs to the record endpoint", async () => {
    const mock = capture(jsonResponse({ status: "recording_started" }, 202));
    await recordCameraClip("cam-1");
    expect(mock.mock.calls[0]?.[0]).toBe("/api/cameras/cam-1/record");
    expect((mock.mock.calls[0]?.[1] as RequestInit).method).toBe("POST");
  });
});

describe("livefeed settings endpoints", () => {
  it("getLiveViewSettings GETs /livefeed/settings/live-view", async () => {
    const mock = capture(
      jsonResponse({
        default_camera_id: null,
        auto_refresh_enabled: false,
        auto_refresh_interval_seconds: 10,
      }),
    );
    await getLiveViewSettings();
    expect(mock.mock.calls[0]?.[0]).toBe("/api/livefeed/settings/live-view");
  });

  it("updateLiveViewSettings PUTs the payload", async () => {
    const mock = capture(
      jsonResponse({
        default_camera_id: null,
        auto_refresh_enabled: true,
        auto_refresh_interval_seconds: 15,
      }),
    );
    await updateLiveViewSettings({
      default_camera_id: null,
      auto_refresh_enabled: true,
      auto_refresh_interval_seconds: 15,
    });
    expect(mock.mock.calls[0]?.[0]).toBe("/api/livefeed/settings/live-view");
    expect((mock.mock.calls[0]?.[1] as RequestInit).method).toBe("PUT");
  });

  it("getSecurityFeedSettings GETs /livefeed/settings/security-feed", async () => {
    const mock = capture(jsonResponse({ camera_ids: [], columns: 2, refresh_interval_seconds: 20 }));
    await getSecurityFeedSettings();
    expect(mock.mock.calls[0]?.[0]).toBe("/api/livefeed/settings/security-feed");
  });

  it("updateSecurityFeedSettings PUTs the payload", async () => {
    const mock = capture(jsonResponse({ camera_ids: [], columns: 3, refresh_interval_seconds: 30 }));
    await updateSecurityFeedSettings({ camera_ids: [], columns: 3, refresh_interval_seconds: 30 });
    expect(mock.mock.calls[0]?.[0]).toBe("/api/livefeed/settings/security-feed");
    expect((mock.mock.calls[0]?.[1] as RequestInit).method).toBe("PUT");
  });
});
