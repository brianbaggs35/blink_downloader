import { describe, expect, it } from "vitest";

import { useMobileNav } from "@/composables/useMobileNav";

describe("useMobileNav", () => {
  it("opens", () => {
    const { open, close, isOpen } = useMobileNav();
    close();
    open();
    expect(isOpen.value).toBe(true);
  });

  it("closes", () => {
    const { open, close, isOpen } = useMobileNav();
    open();
    close();
    expect(isOpen.value).toBe(false);
  });

  it("toggles from closed to open and back", () => {
    const { close, toggle, isOpen } = useMobileNav();
    close();
    toggle();
    expect(isOpen.value).toBe(true);
    toggle();
    expect(isOpen.value).toBe(false);
  });

  it("shares state across separate calls", () => {
    const a = useMobileNav();
    const b = useMobileNav();
    a.open();
    expect(b.isOpen.value).toBe(true);
    a.close();
  });
});
