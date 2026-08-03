import { describe, expect, it, vi } from "vitest";

import {
  clipFrameUrl,
  createPerson,
  deleteFace,
  deletePerson,
  detectFacesInClipFrame,
  enrollFace,
  faceThumbnailUrl,
  getBiometricsSettings,
  getPerson,
  listPeople,
  listPersonFaces,
  personThumbnailUrl,
  reportFalsePositive,
  updateBiometricsSettings,
  updatePerson,
  verifyBiometricsModel,
} from "@/api";
import { jsonResponse } from "./helpers";

function capture(response: Response) {
  const mock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", mock);
  return mock;
}

const settingsFixture = {
  enabled: false,
  model_pack: "buffalo_l" as const,
  execution_provider_preference: "auto" as const,
  recognition_threshold: 0.4,
  available_providers: ["CPUExecutionProvider"],
  model_download_status: "idle" as const,
  model_download_error: null,
  model_download_providers: [] as string[],
  updated_at: "2026-07-25T00:00:00Z",
};

const personFixture = {
  id: "person-1",
  name: "Alex",
  has_thumbnail: false,
  face_count: 0,
  created_at: "2026-07-25T00:00:00Z",
  updated_at: "2026-07-25T00:00:00Z",
};

describe("biometrics settings endpoints", () => {
  it("getBiometricsSettings GETs /biometrics/settings", async () => {
    const mock = capture(jsonResponse(settingsFixture));
    await getBiometricsSettings();
    expect(mock.mock.calls[0]?.[0]).toBe("/api/biometrics/settings");
  });

  it("updateBiometricsSettings PUTs the payload", async () => {
    const mock = capture(jsonResponse(settingsFixture));
    await updateBiometricsSettings({
      enabled: true,
      model_pack: "buffalo_sc",
      execution_provider_preference: "cpu",
      recognition_threshold: 0.5,
    });
    expect(mock.mock.calls[0]?.[0]).toBe("/api/biometrics/settings");
    expect((mock.mock.calls[0]?.[1] as RequestInit).method).toBe("PUT");
  });

  it("verifyBiometricsModel POSTs to settings/verify-model", async () => {
    const mock = capture(jsonResponse(settingsFixture));
    await verifyBiometricsModel();
    expect(mock.mock.calls[0]?.[0]).toBe("/api/biometrics/settings/verify-model");
    expect((mock.mock.calls[0]?.[1] as RequestInit).method).toBe("POST");
  });
});

describe("people endpoints", () => {
  it("listPeople GETs /biometrics/people", async () => {
    const mock = capture(jsonResponse([]));
    await listPeople();
    expect(mock.mock.calls[0]?.[0]).toBe("/api/biometrics/people");
  });

  it("getPerson GETs by id", async () => {
    const mock = capture(jsonResponse(personFixture));
    await getPerson("person-1");
    expect(mock.mock.calls[0]?.[0]).toBe("/api/biometrics/people/person-1");
  });

  it("createPerson posts the name", async () => {
    const mock = capture(jsonResponse(personFixture));
    await createPerson({ name: "Alex" });
    expect(mock.mock.calls[0]?.[0]).toBe("/api/biometrics/people");
    const init = mock.mock.calls[0]?.[1] as RequestInit;
    expect(JSON.parse(init.body as string)).toEqual({ name: "Alex" });
  });

  it("updatePerson PUTs the new name", async () => {
    const mock = capture(jsonResponse({ ...personFixture, name: "New Name" }));
    await updatePerson("person-1", { name: "New Name", never_mark_suspicious: false });
    expect(mock.mock.calls[0]?.[0]).toBe("/api/biometrics/people/person-1");
    expect((mock.mock.calls[0]?.[1] as RequestInit).method).toBe("PUT");
  });

  it("deletePerson DELETEs by id", async () => {
    const mock = capture(new Response(null, { status: 204 }));
    await deletePerson("person-1");
    expect(mock.mock.calls[0]?.[0]).toBe("/api/biometrics/people/person-1");
    expect((mock.mock.calls[0]?.[1] as RequestInit).method).toBe("DELETE");
  });

  it("builds the person thumbnail URL directly", () => {
    expect(personThumbnailUrl("person-1")).toBe("/api/biometrics/people/person-1/thumbnail");
  });
});

describe("face sample endpoints", () => {
  it("listPersonFaces GETs the person's faces", async () => {
    const mock = capture(jsonResponse([]));
    await listPersonFaces("person-1");
    expect(mock.mock.calls[0]?.[0]).toBe("/api/biometrics/people/person-1/faces");
  });

  it("builds the face thumbnail URL directly", () => {
    expect(faceThumbnailUrl("person-1", "face-1")).toBe(
      "/api/biometrics/people/person-1/faces/face-1/thumbnail",
    );
  });

  it("deleteFace DELETEs the sample", async () => {
    const mock = capture(new Response(null, { status: 204 }));
    await deleteFace("person-1", "face-1");
    expect(mock.mock.calls[0]?.[0]).toBe("/api/biometrics/people/person-1/faces/face-1");
    expect((mock.mock.calls[0]?.[1] as RequestInit).method).toBe("DELETE");
  });
});

describe("clip frame + enrollment endpoints", () => {
  it("builds the clip frame URL with the frame_seconds query param", () => {
    expect(clipFrameUrl("clip-1", 2.5)).toBe("/api/biometrics/clips/clip-1/frame?frame_seconds=2.5");
  });

  it("detectFacesInClipFrame GETs with the frame_seconds query param", async () => {
    const mock = capture(jsonResponse([]));
    await detectFacesInClipFrame("clip-1", 2.5);
    expect(mock.mock.calls[0]?.[0]).toBe(
      "/api/biometrics/clips/clip-1/detect-faces?frame_seconds=2.5",
    );
  });

  it("enrollFace posts the clip id, frame time, and bbox", async () => {
    const mock = capture(
      jsonResponse({
        id: "face-1",
        source_clip_id: "clip-1",
        source_frame_seconds: 2.5,
        created_at: "2026-07-25T00:00:00Z",
      }),
    );
    await enrollFace("person-1", {
      clip_id: "clip-1",
      frame_seconds: 2.5,
      bbox: [0.1, 0.2, 0.3, 0.4],
    });
    expect(mock.mock.calls[0]?.[0]).toBe("/api/biometrics/people/person-1/enroll");
    const init = mock.mock.calls[0]?.[1] as RequestInit;
    expect(JSON.parse(init.body as string)).toEqual({
      clip_id: "clip-1",
      frame_seconds: 2.5,
      bbox: [0.1, 0.2, 0.3, 0.4],
    });
  });

  it("reportFalsePositive POSTs to the clip+person report endpoint", async () => {
    const mock = capture(jsonResponse({ negative_sample_captured: true }));
    await reportFalsePositive("clip-1", "person-1");
    expect(mock.mock.calls[0]?.[0]).toBe(
      "/api/biometrics/clips/clip-1/people/person-1/report-false-positive",
    );
    expect((mock.mock.calls[0]?.[1] as RequestInit).method).toBe("POST");
  });
});
