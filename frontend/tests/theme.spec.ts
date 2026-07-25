import { describe, expect, it } from "vitest";

import { initTheme, useTheme } from "@/composables/useTheme";

describe("useTheme", () => {
  it("defaults to dark", () => {
    initTheme();
    expect(document.documentElement.classList.contains("blink-dark")).toBe(true);
    expect(useTheme().isDark.value).toBe(true);
  });

  it("honors a stored light preference", () => {
    localStorage.setItem("blink-theme", "light");
    initTheme();
    expect(document.documentElement.classList.contains("blink-dark")).toBe(false);
  });

  it("toggles and persists", () => {
    initTheme();
    const { toggle, isDark } = useTheme();
    toggle();
    expect(isDark.value).toBe(false);
    expect(localStorage.getItem("blink-theme")).toBe("light");
    expect(document.documentElement.classList.contains("blink-dark")).toBe(false);
    toggle();
    expect(localStorage.getItem("blink-theme")).toBe("dark");
    expect(document.documentElement.classList.contains("blink-dark")).toBe(true);
  });

  it("sets an explicit value", () => {
    initTheme();
    const { setDark, isDark } = useTheme();
    setDark(false);
    expect(isDark.value).toBe(false);
    setDark(true);
    expect(isDark.value).toBe(true);
  });
});
