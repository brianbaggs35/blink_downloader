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

export type AIProviderKind = components["schemas"]["AIProviderKind"];
export type AISettingsRead = components["schemas"]["AISettingsRead"];
export type AISettingsUpdate = components["schemas"]["AISettingsUpdate"];
export type AIConnectionTestRequest = components["schemas"]["AIConnectionTestRequest"];
export type AIConnectionTestResponse = components["schemas"]["AIConnectionTestResponse"];

export type AnalysisRead = components["schemas"]["AnalysisRead"];
export type DetectedEntityRead = components["schemas"]["DetectedEntityRead"];
export type SuspicionLabel = components["schemas"]["SuspicionLabel"];
export type FeedbackCreate = components["schemas"]["FeedbackCreate"];
export type FeedbackRead = components["schemas"]["FeedbackRead"];
export type FeedbackVerdict = components["schemas"]["FeedbackVerdict"];

export type VehicleRead = components["schemas"]["VehicleRead"];
export type VehicleUpdate = components["schemas"]["VehicleUpdate"];
export type ProximityEventRead = components["schemas"]["ProximityEventRead"];

export type AlertSettingsRead = components["schemas"]["AlertSettingsRead"];
export type AlertSettingsUpdate = components["schemas"]["AlertSettingsUpdate"];
export type AlertTestResponse = components["schemas"]["AlertTestResponse"];

export type AiStatsResponse = components["schemas"]["AiStatsResponse"];
export type AiUsageResponse = components["schemas"]["AiUsageResponse"];

export type UserCreate = components["schemas"]["UserCreate"];

export type ModelPack = components["schemas"]["ModelPack"];
export type ExecutionProviderPreference = components["schemas"]["ExecutionProviderPreference"];
export type BiometricsSettingsRead = components["schemas"]["BiometricsSettingsRead"];
export type BiometricsSettingsUpdate = components["schemas"]["BiometricsSettingsUpdate"];
export type PersonRead = components["schemas"]["PersonRead"];
export type PersonCreate = components["schemas"]["PersonCreate"];
export type PersonUpdate = components["schemas"]["PersonUpdate"];
export type FaceEmbeddingRead = components["schemas"]["FaceEmbeddingRead"];
export type DetectedFaceRead = components["schemas"]["DetectedFaceRead"];
export type EnrollFaceRequest = components["schemas"]["EnrollFaceRequest"];
export type RecognizedPersonRead = components["schemas"]["RecognizedPersonRead"];
export type VerifyModelRead = components["schemas"]["VerifyModelRead"];
export type ReportFalsePositiveRead = components["schemas"]["ReportFalsePositiveRead"];

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

export function updateCamera(
  id: string,
  enabled: boolean,
  securityContext: string | null = null,
): Promise<CameraRead> {
  return api<CameraRead>(`/cameras/${id}`, {
    method: "PATCH",
    json: { enabled, security_context: securityContext },
  });
}

// ------------------------------------------------------------------- Clips

export type ClipListParams = {
  camera_id?: string;
  since?: string;
  until?: string;
  downloaded_only?: boolean;
  recognized_person_id?: string;
  has_recognized_person?: boolean;
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

export function getClipAnalysis(clipId: string): Promise<AnalysisRead> {
  return api<AnalysisRead>(`/clips/${clipId}/analysis`);
}

export function reanalyzeClip(clipId: string): Promise<{ status: string }> {
  return api<{ status: string }>(`/clips/${clipId}/reanalyze`, { method: "POST" });
}

export function bulkAnalyzeClips(clipIds: string[]): Promise<BulkActionResponse> {
  return api<BulkActionResponse>("/clips/bulk-analyze", { json: { clip_ids: clipIds } });
}

export function submitFeedback(clipId: string, body: FeedbackCreate): Promise<FeedbackRead> {
  return api<FeedbackRead>(`/clips/${clipId}/feedback`, { json: body });
}

export function listFeedback(clipId: string): Promise<FeedbackRead[]> {
  return api<FeedbackRead[]>(`/clips/${clipId}/feedback`);
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

export function getAiSettings(): Promise<AISettingsRead> {
  return api<AISettingsRead>("/settings/ai");
}

export function updateAiSettings(body: AISettingsUpdate): Promise<AISettingsRead> {
  return api<AISettingsRead>("/settings/ai", { method: "PUT", json: body });
}

export function testAiConnection(
  body: AIConnectionTestRequest,
): Promise<AIConnectionTestResponse> {
  return api<AIConnectionTestResponse>("/settings/ai/test-connection", { json: body });
}

// ---------------------------------------------------------------- Vehicles

export function listVehicles(): Promise<VehicleRead[]> {
  return api<VehicleRead[]>("/vehicles");
}

export function getVehicle(cameraId: string): Promise<VehicleRead> {
  return api<VehicleRead>(`/vehicles/${cameraId}`);
}

export function putVehicle(cameraId: string, body: VehicleUpdate): Promise<VehicleRead> {
  return api<VehicleRead>(`/vehicles/${cameraId}`, { method: "PUT", json: body });
}

export function deleteVehicle(cameraId: string): Promise<void> {
  return api<void>(`/vehicles/${cameraId}`, { method: "DELETE" });
}

export function captureVehicleReferenceFrame(cameraId: string): Promise<void> {
  return api<void>(`/vehicles/${cameraId}/reference-frame`, { method: "POST" });
}

export function vehicleReferenceFrameUrl(cameraId: string): string {
  return `/api/vehicles/${cameraId}/reference-frame`;
}

export function listProximityEvents(cameraId: string): Promise<ProximityEventRead[]> {
  return api<ProximityEventRead[]>(`/vehicles/${cameraId}/proximity-events`);
}

// ------------------------------------------------------------------ Alerts

export function getAlertSettings(): Promise<AlertSettingsRead> {
  return api<AlertSettingsRead>("/alerts/settings");
}

export function updateAlertSettings(body: AlertSettingsUpdate): Promise<AlertSettingsRead> {
  return api<AlertSettingsRead>("/alerts/settings", { method: "PUT", json: body });
}

export function testAlertChannels(): Promise<AlertTestResponse> {
  return api<AlertTestResponse>("/alerts/settings/test", { method: "POST" });
}

// --------------------------------------------------------------- AI stats

export function getAiStats(): Promise<AiStatsResponse> {
  return api<AiStatsResponse>("/ai/stats");
}

export function getAiUsage(): Promise<AiUsageResponse> {
  return api<AiUsageResponse>("/ai/usage");
}

// ------------------------------------------------------------------ Users

export function listUsers(): Promise<UserRead[]> {
  return api<UserRead[]>("/users");
}

export function createUser(body: UserCreate): Promise<UserRead> {
  return api<UserRead>("/users", { json: body });
}

// -------------------------------------------------------------- Biometrics

export function getBiometricsSettings(): Promise<BiometricsSettingsRead> {
  return api<BiometricsSettingsRead>("/biometrics/settings");
}

export function updateBiometricsSettings(
  body: BiometricsSettingsUpdate,
): Promise<BiometricsSettingsRead> {
  return api<BiometricsSettingsRead>("/biometrics/settings", { method: "PUT", json: body });
}

export function listPeople(): Promise<PersonRead[]> {
  return api<PersonRead[]>("/biometrics/people");
}

export function getPerson(personId: string): Promise<PersonRead> {
  return api<PersonRead>(`/biometrics/people/${personId}`);
}

export function createPerson(body: PersonCreate): Promise<PersonRead> {
  return api<PersonRead>("/biometrics/people", { json: body });
}

export function updatePerson(personId: string, body: PersonUpdate): Promise<PersonRead> {
  return api<PersonRead>(`/biometrics/people/${personId}`, { method: "PUT", json: body });
}

export function deletePerson(personId: string): Promise<void> {
  return api<void>(`/biometrics/people/${personId}`, { method: "DELETE" });
}

export function personThumbnailUrl(personId: string): string {
  return `/api/biometrics/people/${personId}/thumbnail`;
}

export function listPersonFaces(personId: string): Promise<FaceEmbeddingRead[]> {
  return api<FaceEmbeddingRead[]>(`/biometrics/people/${personId}/faces`);
}

export function faceThumbnailUrl(personId: string, faceId: string): string {
  return `/api/biometrics/people/${personId}/faces/${faceId}/thumbnail`;
}

export function deleteFace(personId: string, faceId: string): Promise<void> {
  return api<void>(`/biometrics/people/${personId}/faces/${faceId}`, { method: "DELETE" });
}

export function clipFrameUrl(clipId: string, frameSeconds: number): string {
  return `/api/biometrics/clips/${clipId}/frame?frame_seconds=${frameSeconds}`;
}

export function detectFacesInClipFrame(
  clipId: string,
  frameSeconds: number,
): Promise<DetectedFaceRead[]> {
  return api<DetectedFaceRead[]>(
    `/biometrics/clips/${clipId}/detect-faces${queryString({ frame_seconds: frameSeconds })}`,
  );
}

export function enrollFace(
  personId: string,
  body: EnrollFaceRequest,
): Promise<FaceEmbeddingRead> {
  return api<FaceEmbeddingRead>(`/biometrics/people/${personId}/enroll`, { json: body });
}

export function verifyBiometricsModel(): Promise<VerifyModelRead> {
  return api<VerifyModelRead>("/biometrics/settings/verify-model", { method: "POST" });
}

export function reportFalsePositive(
  clipId: string,
  personId: string,
): Promise<ReportFalsePositiveRead> {
  return api<ReportFalsePositiveRead>(
    `/biometrics/clips/${clipId}/people/${personId}/report-false-positive`,
    { method: "POST" },
  );
}
