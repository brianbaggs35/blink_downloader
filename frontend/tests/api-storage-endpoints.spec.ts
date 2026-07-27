import { describe, expect, it, vi } from "vitest";

import {
  archiveClips,
  getClipTemporaryLink,
  getStorageIntegrationSettings,
  getStorageSummary,
  googleDriveOAuthStartUrl,
  onedriveOAuthStartUrl,
  restoreClips,
  testStorageIntegrations,
  updateStorageIntegrationSettings,
} from "@/api";
import { jsonResponse } from "./helpers";

function capture(response: Response) {
  const mock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", mock);
  return mock;
}

describe("storage integration settings endpoints", () => {
  it("getStorageIntegrationSettings GETs /settings/storage-integrations", async () => {
    const mock = capture(
      jsonResponse({
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
        auto_archive_backend: "local",
      }),
    );
    await getStorageIntegrationSettings();
    expect(mock.mock.calls[0]?.[0]).toBe("/api/settings/storage-integrations");
    expect((mock.mock.calls[0]?.[1] as RequestInit | undefined)?.method ?? "GET").toBe("GET");
  });

  it("updateStorageIntegrationSettings PUTs the payload", async () => {
    const mock = capture(
      jsonResponse({
        s3_enabled: true,
        s3_bucket: "my-bucket",
        s3_region: "us-east-1",
        s3_prefix: null,
        s3_credentials_set: true,
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
        auto_archive_backend: "s3",
      }),
    );
    await updateStorageIntegrationSettings({
      s3_enabled: true,
      s3_bucket: "my-bucket",
      s3_region: "us-east-1",
      google_drive_enabled: false,
      onedrive_enabled: false,
      auto_archive_backend: "s3",
    });
    expect(mock.mock.calls[0]?.[0]).toBe("/api/settings/storage-integrations");
    expect((mock.mock.calls[0]?.[1] as RequestInit).method).toBe("PUT");
  });

  it("testStorageIntegrations POSTs to the test endpoint", async () => {
    const mock = capture(
      jsonResponse({ s3: { ok: true, detail: "Connected." }, google_drive: null, onedrive: null }),
    );
    await testStorageIntegrations();
    expect(mock.mock.calls[0]?.[0]).toBe("/api/settings/storage-integrations/test");
    expect((mock.mock.calls[0]?.[1] as RequestInit).method).toBe("POST");
  });

  it("googleDriveOAuthStartUrl builds the connect URL", () => {
    expect(googleDriveOAuthStartUrl()).toBe(
      "/api/settings/storage-integrations/google-drive/oauth/start",
    );
  });

  it("onedriveOAuthStartUrl builds the connect URL", () => {
    expect(onedriveOAuthStartUrl()).toBe("/api/settings/storage-integrations/onedrive/oauth/start");
  });
});

describe("storage tab endpoints", () => {
  it("getStorageSummary GETs /storage/summary", async () => {
    const mock = capture(jsonResponse({ by_backend: [], total_clips: 0, total_bytes: 0 }));
    await getStorageSummary();
    expect(mock.mock.calls[0]?.[0]).toBe("/api/storage/summary");
  });

  it("archiveClips POSTs clip ids and a backend", async () => {
    const mock = capture(jsonResponse({ succeeded: 1, failed: 0 }));
    await archiveClips(["clip-1", "clip-2"], "google_drive");
    expect(mock.mock.calls[0]?.[0]).toBe("/api/storage/archive");
    const init = mock.mock.calls[0]?.[1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      clip_ids: ["clip-1", "clip-2"],
      backend: "google_drive",
    });
  });

  it("restoreClips POSTs clip ids", async () => {
    const mock = capture(jsonResponse({ succeeded: 1, failed: 0 }));
    await restoreClips(["clip-1"]);
    expect(mock.mock.calls[0]?.[0]).toBe("/api/storage/restore");
    const init = mock.mock.calls[0]?.[1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ clip_ids: ["clip-1"] });
  });

  it("getClipTemporaryLink POSTs to the clip's link endpoint", async () => {
    const mock = capture(
      jsonResponse({ url: "https://example.com/x", expires_at: "2026-07-27T00:00:00Z" }),
    );
    await getClipTemporaryLink("clip-1");
    expect(mock.mock.calls[0]?.[0]).toBe("/api/storage/clips/clip-1/link");
    expect((mock.mock.calls[0]?.[1] as RequestInit).method).toBe("POST");
  });
});
