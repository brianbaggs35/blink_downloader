import { afterEach, beforeEach, vi } from "vitest";

beforeEach(() => {
  // No unit test should ever reach the real network - anything that gets
  // here forgot to mock the @/api function it calls (or, for endpoint specs
  // that stub fetch directly, hasn't stubbed it yet for this test). Failing
  // fast and loud beats a real, slow connection attempt against a
  // nonexistent server - individual tests that legitimately stub fetch
  // themselves (see tests/api-*-endpoints.spec.ts) simply override this
  // afterwards, since vi.stubGlobal is last-write-wins.
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.reject(new Error("Unmocked fetch() call in a unit test"))),
  );
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  localStorage.clear();
  document.documentElement.className = "";
});
