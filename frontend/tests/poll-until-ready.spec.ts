import { describe, expect, it, vi } from "vitest";

import { pollUntilReady } from "@/lib/pollUntilReady";

describe("pollUntilReady", () => {
  it("calls fetchFn once and stops immediately if isReady is already true", async () => {
    const fetchFn = vi.fn().mockResolvedValue(undefined);
    await pollUntilReady(fetchFn, () => true, 6, 1500);
    expect(fetchFn).toHaveBeenCalledTimes(1);
  });

  it("retries with a delay between attempts until isReady becomes true", async () => {
    const fetchFn = vi.fn().mockResolvedValue(undefined);
    let calls = 0;
    fetchFn.mockImplementation(() => {
      calls += 1;
      return Promise.resolve();
    });
    vi.useFakeTimers();
    try {
      const promise = pollUntilReady(fetchFn, () => calls >= 3, 6, 1500);
      await vi.runAllTimersAsync();
      await promise;
    } finally {
      vi.useRealTimers();
    }
    expect(fetchFn).toHaveBeenCalledTimes(3);
  });

  it("stops after exhausting attempts even if isReady never becomes true", async () => {
    const fetchFn = vi.fn().mockResolvedValue(undefined);
    vi.useFakeTimers();
    try {
      const promise = pollUntilReady(fetchFn, () => false, 4, 1500);
      await vi.runAllTimersAsync();
      await promise;
    } finally {
      vi.useRealTimers();
    }
    expect(fetchFn).toHaveBeenCalledTimes(4);
  });

  it("propagates a fetchFn failure immediately rather than retrying it", async () => {
    const fetchFn = vi.fn().mockRejectedValue(new Error("boom"));
    await expect(pollUntilReady(fetchFn, () => false, 6, 1500)).rejects.toThrow("boom");
    expect(fetchFn).toHaveBeenCalledTimes(1);
  });
});
