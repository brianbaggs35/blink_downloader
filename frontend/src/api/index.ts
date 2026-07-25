/** Typed endpoint functions. Types come from the generated OpenAPI schema. */

import { api, ApiError } from "./client";

import type { components } from "./schema";

export type UserRead = components["schemas"]["UserRead"];
export type UserUpdate = components["schemas"]["UserUpdate"];
export type SetupRequest = components["schemas"]["SetupRequest"];
export type SetupStatus = components["schemas"]["SetupStatus"];
export type HealthReport = components["schemas"]["HealthReport"];

export type BlinkLinkResponse = components["schemas"]["BlinkLinkResponse"];
export type BlinkStatusResponse = components["schemas"]["BlinkStatusResponse"];

export type CameraRead = components["schemas"]["CameraRead"];

export type ClipRead = components["schemas"]["ClipRead"];
export type ClipListResponse = components["schemas"]["ClipListResponse"];
export type BulkActionResponse = components["schemas"]["BulkActionResponse"];

export type StorageSettingsRead = components["schemas"]["StorageSettingsRead"];
export type StorageSettingsUpdate = components["schemas"]["StorageSettingsUpdate"];

export { ApiError } from "./client";

export function getHealth(): Promise<HealthReport> {
  // A degraded system responds 503 with the same report body.
  return api<HealthReport>("/health", { allow: [503] });
}

export function getSetupStatus(): Promise<SetupStatus> {
  return api<SetupStatus>("/setup/status");
}

export function runSetup(body: SetupRequest): Promise<UserRead> {
  return api<UserRead>("/setup", { json: body });
}

export function login(email: string, password: string): Promise<void> {
  return api<void>("/auth/login", { form: { username: email, password } });
}

export function logout(): Promise<void> {
  return api<void>("/auth/logout", { method: "POST" });
}

export function getMe(): Promise<UserRead> {
  return api<UserRead>("/users/me");
}

export function updateMe(body: UserUpdate): Promise<UserRead> {
  return api<UserRead>("/users/me", { method: "PATCH", json: body });
}

// ------------------------------------------------------------------- Blink

export function linkBlinkAccount(username: string, password: string): Promise<BlinkLinkResponse> {
  return api<BlinkLinkResponse>("/blink/link", { json: { username, password } });
}

export function verifyBlinkAccount(
  linkSessionId: string,
  code: string,
): Promise<BlinkLinkResponse> {
  return api<BlinkLinkResponse>("/blink/verify", {
    json: { link_session_id: linkSessionId, code },
  });
}

export function getBlinkStatus(): Promise<BlinkStatusResponse> {
  return api<BlinkStatusResponse>("/blink/status");
}

export function triggerBlinkSync(): Promise<{ status: string }> {
  return api<{ status: string }>("/blink/sync", { method: "POST" });
}

export function unlinkBlinkAccount(): Promise<void> {
  return api<void>("/blink/account", { method: "DELETE" });
}

// ----------------------------------------------------------------- Cameras

export function listCameras(): Promise<CameraRead[]> {
  return api<CameraRead[]>("/cameras");
}

export function updateCamera(id: string, enabled: boolean): Promise<CameraRead> {
  return api<CameraRead>(`/cameras/${id}`, { method: "PATCH", json: { enabled } });
}

// ------------------------------------------------------------------- Clips

export type ClipListParams = {
  camera_id?: string;
  since?: string;
  until?: string;
  downloaded_only?: boolean;
  page?: number;
  page_size?: number;
};

function queryString(params: Record<string, unknown>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) {
      search.set(key, String(value));
    }
  }
  const asString = search.toString();
  return asString ? `?${asString}` : "";
}

export function listClips(params: ClipListParams = {}): Promise<ClipListResponse> {
  return api<ClipListResponse>(`/clips${queryString(params)}`);
}

export function getClip(id: string): Promise<ClipRead> {
  return api<ClipRead>(`/clips/${id}`);
}

export function deleteClip(id: string): Promise<void> {
  return api<void>(`/clips/${id}`, { method: "DELETE" });
}

export function bulkDeleteClips(clipIds: string[]): Promise<BulkActionResponse> {
  return api<BulkActionResponse>("/clips/bulk-delete", { json: { clip_ids: clipIds } });
}

/** Not fetch()-based: this URL is meant for <video src>/<img src> directly. */
export function clipStreamUrl(id: string): string {
  return `/api/clips/${id}/stream`;
}

export function clipThumbnailUrl(id: string): string {
  return `/api/clips/${id}/thumbnail`;
}

export function clipDownloadUrl(id: string): string {
  return `/api/clips/${id}/download`;
}

/** POSTs clip ids, receives a zip blob, and triggers a browser download —
 * distinct from the simple GET-anchor pattern used for a single clip since
 * this endpoint needs a POST body. */
export async function downloadClipsAsZip(clipIds: string[]): Promise<void> {
  const response = await fetch("/api/clips/bulk-download", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ clip_ids: clipIds }),
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: string };
      detail = body.detail ?? detail;
    } catch {
      // body wasn't JSON — keep statusText
    }
    throw new ApiError(response.status, detail);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const filenameMatch = /filename="?([^"]+)"?/.exec(
    response.headers.get("content-disposition") ?? "",
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = filenameMatch?.[1] ?? "clips.zip";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------- Settings

export function getStorageSettings(): Promise<StorageSettingsRead> {
  return api<StorageSettingsRead>("/settings/storage");
}

export function updateStorageSettings(
  body: StorageSettingsUpdate,
): Promise<StorageSettingsRead> {
  return api<StorageSettingsRead>("/settings/storage", { method: "PATCH", json: body });
}
