/** Typed endpoint functions. Types come from the generated OpenAPI schema. */

import { api } from "./client";

import type { components } from "./schema";

export type UserRead = components["schemas"]["UserRead"];
export type UserUpdate = components["schemas"]["UserUpdate"];
export type SetupRequest = components["schemas"]["SetupRequest"];
export type SetupStatus = components["schemas"]["SetupStatus"];
export type HealthReport = components["schemas"]["HealthReport"];

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
