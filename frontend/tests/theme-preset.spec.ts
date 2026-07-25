import { describe, expect, it } from "vitest";

import { BlinkPreset, primeVueOptions } from "@/theme";

interface PresetShape {
  semantic: {
    primary: Record<string, string>;
    colorScheme: {
      light: { surface: Record<string, string> };
      dark: { surface: Record<string, string> };
    };
  };
}

describe("theme preset", () => {
  it("uses the cyan primary scale over slate surfaces", () => {
    const preset = BlinkPreset as unknown as PresetShape;
    expect(preset.semantic.primary["500"]).toBe("#06b6d4");
    expect(preset.semantic.colorScheme.light.surface["950"]).toBe("#020617");
    expect(preset.semantic.colorScheme.dark.surface["0"]).toBe("#ffffff");
  });

  it("binds dark mode to the blink-dark class", () => {
    expect(primeVueOptions.theme.options.darkModeSelector).toBe(".blink-dark");
    expect(primeVueOptions.theme.preset).toBe(BlinkPreset);
  });
});
