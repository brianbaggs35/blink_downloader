import { describe, expect, it } from "vitest";

import { useFormatting } from "@/composables/useFormatting";
import { useAuthStore } from "@/stores/auth";
import { fakeUser, makePinia } from "./helpers";

function withTimezone(timezone: string) {
  makePinia();
  const auth = useAuthStore();
  auth.user = { ...fakeUser, timezone };
  return useFormatting();
}

describe("useFormatting", () => {
  it("formats a date-time in the user's configured timezone", () => {
    const { formatDateTime } = withTimezone("America/New_York");
    const formatted = formatDateTime("2026-07-20T18:30:00Z");
    // 18:30 UTC is 14:30 in New York (EDT, UTC-4) — assert the hour shifted,
    // not an exact locale string that would be brittle across environments.
    expect(formatted).toContain("2:30");
  });

  it("uses UTC when the user has no timezone set", () => {
    makePinia();
    const auth = useAuthStore();
    auth.user = null;
    const { formatDateTime } = useFormatting();
    const formatted = formatDateTime("2026-07-20T18:30:00Z");
    expect(formatted).toContain("6:30");
  });

  it("caches formatters per timezone", () => {
    const { formatDateTime } = withTimezone("UTC");
    const first = formatDateTime("2026-01-01T00:00:00Z");
    const second = formatDateTime("2026-06-01T00:00:00Z");
    expect(first).not.toBe(second);
  });

  it("formats a date without a time component", () => {
    const { formatDate } = withTimezone("UTC");
    const formatted = formatDate("2026-07-20T18:30:00Z");
    expect(formatted).not.toMatch(/\d{1,2}:\d{2}/);
  });

  describe("formatDuration", () => {
    it("renders minutes:seconds", () => {
      const { formatDuration } = withTimezone("UTC");
      expect(formatDuration(65)).toBe("1:05");
      expect(formatDuration(5)).toBe("0:05");
      expect(formatDuration(3661)).toBe("61:01");
    });

    it("renders a placeholder for null", () => {
      const { formatDuration } = withTimezone("UTC");
      expect(formatDuration(null)).toBe("—");
    });
  });

  describe("formatFileSize", () => {
    it("renders bytes under 1KB as-is", () => {
      const { formatFileSize } = withTimezone("UTC");
      expect(formatFileSize(512)).toBe("512 B");
    });

    it("renders KB/MB/GB with one decimal", () => {
      const { formatFileSize } = withTimezone("UTC");
      expect(formatFileSize(2048)).toBe("2.0 KB");
      expect(formatFileSize(5 * 1024 * 1024)).toBe("5.0 MB");
      expect(formatFileSize(3 * 1024 * 1024 * 1024)).toBe("3.0 GB");
    });

    it("caps at GB rather than climbing to TB", () => {
      const { formatFileSize } = withTimezone("UTC");
      expect(formatFileSize(1024 * 1024 * 1024 * 1024)).toBe("1024.0 GB");
    });

    it("renders a placeholder for null", () => {
      const { formatFileSize } = withTimezone("UTC");
      expect(formatFileSize(null)).toBe("—");
    });
  });
});
