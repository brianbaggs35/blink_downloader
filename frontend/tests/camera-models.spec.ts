import { describe, expect, it } from "vitest";

import { cameraModelLabel } from "@/lib/cameraModels";

describe("cameraModelLabel", () => {
  it.each([
    ["catalina", "Blink Outdoor Gen 3"],
    ["sonoran", "Blink Outdoor 4 (2K+)"],
    ["superior", "Blink Floodlight Camera"],
    ["owl", "Blink Mini"],
    ["doorbell", "Blink Video Doorbell"],
    ["lotus", "Blink Video Doorbell"],
  ])("maps %s to %s", (cameraType, expected) => {
    expect(cameraModelLabel(cameraType)).toBe(expected);
  });

  it("is case-insensitive", () => {
    expect(cameraModelLabel("CATALINA")).toBe("Blink Outdoor Gen 3");
  });

  it("falls back to the raw codename for anything unmapped, rather than guessing", () => {
    expect(cameraModelLabel("sedona")).toBe("sedona");
  });
});
