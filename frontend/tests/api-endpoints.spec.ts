import { describe, expect, it, vi } from "vitest";

import {
  getHealth,
  getMe,
  getSetupStatus,
  login,
  logout,
  runSetup,
  updateMe,
} from "@/api";
import { fakeUser, healthyReport, jsonResponse } from "./helpers";

function capture(response: Response) {
  const mock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", mock);
  return mock;
}

describe("api endpoints", () => {
  it("getHealth tolerates a degraded 503 body", async () => {
    capture(jsonResponse({ ...healthyReport, status: "degraded" }, 503));
    const report = await getHealth();
    expect(report.status).toBe("degraded");
  });

  it("getSetupStatus GETs /setup/status", async () => {
    const mock = capture(jsonResponse({ initialized: false }));
    await getSetupStatus();
    expect(mock.mock.calls[0]?.[0]).toBe("/api/setup/status");
  });

  it("runSetup POSTs the payload", async () => {
    const mock = capture(jsonResponse(fakeUser, 201));
    await runSetup({ email: "a@b.com", password: "p".repeat(12), display_name: "A" });
    expect(mock.mock.calls[0]?.[0]).toBe("/api/setup");
    expect((mock.mock.calls[0]?.[1] as RequestInit).method).toBe("POST");
  });

  it("login submits form credentials", async () => {
    const mock = capture(new Response(null, { status: 204 }));
    await login("a@b.com", "secret");
    expect(mock.mock.calls[0]?.[0]).toBe("/api/auth/login");
    expect(String((mock.mock.calls[0]?.[1] as RequestInit).body)).toContain("username=a%40b.com");
  });

  it("logout POSTs with no body", async () => {
    const mock = capture(new Response(null, { status: 204 }));
    await logout();
    expect(mock.mock.calls[0]?.[0]).toBe("/api/auth/logout");
    expect((mock.mock.calls[0]?.[1] as RequestInit).method).toBe("POST");
  });

  it("getMe and updateMe hit /users/me", async () => {
    const mock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse(fakeUser)));
    vi.stubGlobal("fetch", mock);
    await getMe();
    await updateMe({ timezone: "UTC" });
    expect(mock.mock.calls[0]?.[0]).toBe("/api/users/me");
    expect((mock.mock.calls[1]?.[1] as RequestInit).method).toBe("PATCH");
  });
});
