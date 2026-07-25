import { describe, expect, it, vi } from "vitest";

import {
  bulkAnalyzeClips,
  captureVehicleReferenceFrame,
  createUser,
  deleteVehicle,
  getAiSettings,
  getAiStats,
  getAiUsage,
  getAlertSettings,
  getClipAnalysis,
  getVehicle,
  listFeedback,
  listProximityEvents,
  listUsers,
  listVehicles,
  putVehicle,
  reanalyzeClip,
  submitFeedback,
  testAiConnection,
  testAlertChannels,
  updateAiSettings,
  updateAlertSettings,
  vehicleReferenceFrameUrl,
} from "@/api";
import { jsonResponse } from "./helpers";

function capture(response: Response) {
  const mock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", mock);
  return mock;
}

describe("clip analysis endpoints", () => {
  it("getClipAnalysis GETs the clip's analysis", async () => {
    const mock = capture(jsonResponse({ id: "an-1" }));
    await getClipAnalysis("clip-1");
    expect(mock.mock.calls[0]?.[0]).toBe("/api/clips/clip-1/analysis");
    expect((mock.mock.calls[0]?.[1] as RequestInit).method).toBe("GET");
  });

  it("reanalyzeClip POSTs to the reanalyze endpoint", async () => {
    const mock = capture(jsonResponse({ status: "queued" }, 202));
    await reanalyzeClip("clip-1");
    expect(mock.mock.calls[0]?.[0]).toBe("/api/clips/clip-1/reanalyze");
    expect((mock.mock.calls[0]?.[1] as RequestInit).method).toBe("POST");
  });

  it("bulkAnalyzeClips posts the id list", async () => {
    const mock = capture(jsonResponse({ succeeded: 2, failed: 0 }));
    await bulkAnalyzeClips(["a", "b"]);
    expect(mock.mock.calls[0]?.[0]).toBe("/api/clips/bulk-analyze");
    const init = mock.mock.calls[0]?.[1] as RequestInit;
    expect(JSON.parse(init.body as string)).toEqual({ clip_ids: ["a", "b"] });
  });

  it("submitFeedback posts the verdict and note", async () => {
    const mock = capture(
      jsonResponse({
        id: "fb-1",
        analysis_id: "an-1",
        user_id: "u-1",
        verdict: "correct",
        note: null,
        applied: true,
        created_at: "2026-07-20T18:00:00Z",
      }),
    );
    await submitFeedback("clip-1", { verdict: "correct", note: null });
    expect(mock.mock.calls[0]?.[0]).toBe("/api/clips/clip-1/feedback");
    const init = mock.mock.calls[0]?.[1] as RequestInit;
    expect(JSON.parse(init.body as string)).toEqual({ verdict: "correct", note: null });
  });

  it("listFeedback GETs the clip's feedback history", async () => {
    const mock = capture(jsonResponse([]));
    await listFeedback("clip-1");
    expect(mock.mock.calls[0]?.[0]).toBe("/api/clips/clip-1/feedback");
  });
});

describe("AI settings endpoints", () => {
  it("getAiSettings GETs /settings/ai", async () => {
    const mock = capture(
      jsonResponse({
        enabled: false,
        tier1_provider: null,
        tier1_model: null,
        tier1_api_key_set: false,
        tier1_base_url: null,
        tier2_enabled: true,
        tier2_provider: null,
        tier2_model: null,
        tier2_api_key_set: false,
        tier2_base_url: null,
        keyframes_per_clip: 4,
        tier2_suspicion_threshold: 0.5,
        feedback_context_count: 5,
      }),
    );
    await getAiSettings();
    expect(mock.mock.calls[0]?.[0]).toBe("/api/settings/ai");
  });

  it("updateAiSettings PUTs the payload", async () => {
    const mock = capture(jsonResponse({ enabled: true }));
    await updateAiSettings({
      enabled: true,
      tier1_provider: "openai",
      tier1_model: "gpt-4o-mini",
      tier1_api_key: null,
      tier1_base_url: null,
      tier2_enabled: false,
      tier2_provider: null,
      tier2_model: null,
      tier2_api_key: null,
      tier2_base_url: null,
      keyframes_per_clip: 4,
      tier2_suspicion_threshold: 0.5,
      feedback_context_count: 5,
    });
    expect(mock.mock.calls[0]?.[0]).toBe("/api/settings/ai");
    expect((mock.mock.calls[0]?.[1] as RequestInit).method).toBe("PUT");
  });

  it("testAiConnection posts the tier/provider/model under test", async () => {
    const mock = capture(jsonResponse({ ok: true, detail: null }));
    await testAiConnection({
      tier: "tier1",
      provider: "openai",
      model: "gpt-4o-mini",
      api_key: null,
      base_url: null,
    });
    expect(mock.mock.calls[0]?.[0]).toBe("/api/settings/ai/test-connection");
  });
});

describe("vehicle endpoints", () => {
  it("listVehicles GETs /vehicles", async () => {
    const mock = capture(jsonResponse([]));
    await listVehicles();
    expect(mock.mock.calls[0]?.[0]).toBe("/api/vehicles");
  });

  it("getVehicle GETs by camera id", async () => {
    const mock = capture(jsonResponse({ id: "veh-1" }));
    await getVehicle("cam-1");
    expect(mock.mock.calls[0]?.[0]).toBe("/api/vehicles/cam-1");
  });

  it("putVehicle PUTs the vehicle payload", async () => {
    const mock = capture(jsonResponse({ id: "veh-1" }));
    await putVehicle("cam-1", {
      description: "My car",
      outline_points: [
        [0.1, 0.1],
        [0.9, 0.1],
        [0.9, 0.9],
      ],
      estimated_length_feet: 15,
      distance_threshold_feet: 6,
      enabled: true,
    });
    expect(mock.mock.calls[0]?.[0]).toBe("/api/vehicles/cam-1");
    expect((mock.mock.calls[0]?.[1] as RequestInit).method).toBe("PUT");
  });

  it("deleteVehicle DELETEs by camera id", async () => {
    const mock = capture(new Response(null, { status: 204 }));
    await deleteVehicle("cam-1");
    expect((mock.mock.calls[0]?.[1] as RequestInit).method).toBe("DELETE");
  });

  it("captureVehicleReferenceFrame POSTs to the reference-frame endpoint", async () => {
    const mock = capture(new Response(null, { status: 204 }));
    await captureVehicleReferenceFrame("cam-1");
    expect(mock.mock.calls[0]?.[0]).toBe("/api/vehicles/cam-1/reference-frame");
    expect((mock.mock.calls[0]?.[1] as RequestInit).method).toBe("POST");
  });

  it("builds the reference frame image URL directly", () => {
    expect(vehicleReferenceFrameUrl("cam-1")).toBe("/api/vehicles/cam-1/reference-frame");
  });

  it("listProximityEvents GETs the camera's breach history", async () => {
    const mock = capture(jsonResponse([]));
    await listProximityEvents("cam-1");
    expect(mock.mock.calls[0]?.[0]).toBe("/api/vehicles/cam-1/proximity-events");
  });
});

describe("alert endpoints", () => {
  it("getAlertSettings GETs /alerts/settings", async () => {
    const mock = capture(
      jsonResponse({
        discord_enabled: false,
        discord_webhook_set: false,
        slack_enabled: false,
        slack_webhook_set: false,
        smtp_enabled: false,
        smtp_host: null,
        smtp_port: 587,
        smtp_username: null,
        smtp_password_set: false,
        smtp_use_tls: true,
        smtp_from_address: null,
        smtp_to_addresses: [],
        alert_on_suspicious_clip: true,
        suspicion_alert_threshold: 0.5,
        alert_on_vehicle_proximity: true,
        quiet_hours_start: null,
        quiet_hours_end: null,
        dedup_window_minutes: 15,
      }),
    );
    await getAlertSettings();
    expect(mock.mock.calls[0]?.[0]).toBe("/api/alerts/settings");
  });

  it("updateAlertSettings PUTs the payload", async () => {
    const mock = capture(jsonResponse({ discord_enabled: true }));
    await updateAlertSettings({
      discord_enabled: false,
      discord_webhook_url: null,
      slack_enabled: false,
      slack_webhook_url: null,
      smtp_enabled: false,
      smtp_host: null,
      smtp_port: 587,
      smtp_username: null,
      smtp_password: null,
      smtp_use_tls: true,
      smtp_from_address: null,
      smtp_to_addresses: [],
      alert_on_suspicious_clip: true,
      suspicion_alert_threshold: 0.5,
      alert_on_vehicle_proximity: true,
      quiet_hours_start: null,
      quiet_hours_end: null,
      dedup_window_minutes: 15,
    });
    expect(mock.mock.calls[0]?.[0]).toBe("/api/alerts/settings");
    expect((mock.mock.calls[0]?.[1] as RequestInit).method).toBe("PUT");
  });

  it("testAlertChannels POSTs to the test endpoint", async () => {
    const mock = capture(jsonResponse({}));
    await testAlertChannels();
    expect(mock.mock.calls[0]?.[0]).toBe("/api/alerts/settings/test");
    expect((mock.mock.calls[0]?.[1] as RequestInit).method).toBe("POST");
  });
});

describe("AI stats endpoints", () => {
  it("getAiStats GETs /ai/stats", async () => {
    const mock = capture(
      jsonResponse({
        total_analyzed: 0,
        suspicious_count: 0,
        uncertain_count: 0,
        routine_count: 0,
        escalated_count: 0,
        analyzed_last_7_days: 0,
        vehicle_proximity_breaches: 0,
        total_feedback: 0,
        correct_feedback: 0,
        false_positive_feedback: 0,
        false_negative_feedback: 0,
      }),
    );
    await getAiStats();
    expect(mock.mock.calls[0]?.[0]).toBe("/api/ai/stats");
  });

  it("getAiUsage GETs /ai/usage", async () => {
    const mock = capture(
      jsonResponse({
        total_tokens: 0,
        total_cost_usd: 0,
        total_calls: 0,
        failed_calls: 0,
        daily: [],
        by_provider: [],
      }),
    );
    await getAiUsage();
    expect(mock.mock.calls[0]?.[0]).toBe("/api/ai/usage");
  });
});

describe("user endpoints", () => {
  it("listUsers GETs /users", async () => {
    const mock = capture(jsonResponse([]));
    await listUsers();
    expect(mock.mock.calls[0]?.[0]).toBe("/api/users");
  });

  it("createUser POSTs the new account", async () => {
    const mock = capture(
      jsonResponse({
        id: "u-2",
        email: "new@example.com",
        is_active: true,
        is_superuser: false,
        is_verified: true,
        display_name: "New",
        timezone: "UTC",
      }),
    );
    await createUser({
      email: "new@example.com",
      password: "a-fine-long-password",
      display_name: "New",
      is_superuser: false,
      is_active: true,
      is_verified: true,
      timezone: "UTC",
    });
    expect(mock.mock.calls[0]?.[0]).toBe("/api/users");
    const init = mock.mock.calls[0]?.[1] as RequestInit;
    expect(JSON.parse(init.body as string)).toMatchObject({ email: "new@example.com" });
  });
});
