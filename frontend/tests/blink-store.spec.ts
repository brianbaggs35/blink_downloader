import { beforeEach, describe, expect, it, vi } from "vitest";

import { makePinia } from "./helpers";

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  getBlinkStatus: vi.fn(),
  linkBlinkAccount: vi.fn(),
  verifyBlinkAccount: vi.fn(),
  triggerBlinkSync: vi.fn(),
  unlinkBlinkAccount: vi.fn(),
}));

import {
  getBlinkStatus,
  linkBlinkAccount,
  triggerBlinkSync,
  unlinkBlinkAccount,
  verifyBlinkAccount,
} from "@/api";
import { useBlinkStore } from "@/stores/blink";

const mockedStatus = vi.mocked(getBlinkStatus);
const mockedLink = vi.mocked(linkBlinkAccount);
const mockedVerify = vi.mocked(verifyBlinkAccount);
const mockedSync = vi.mocked(triggerBlinkSync);
const mockedUnlink = vi.mocked(unlinkBlinkAccount);

const unlinkedStatus = {
  linked: false,
  status: null,
  last_sync: null,
  last_error: null,
  camera_count: 0,
};

const linkedStatus = {
  linked: true,
  status: "active" as const,
  last_sync: "2026-07-20T00:00:00Z",
  last_error: null,
  camera_count: 2,
};

beforeEach(() => {
  makePinia();
  vi.clearAllMocks();
});

describe("useBlinkStore", () => {
  it("starts with no status and isLinked false", () => {
    const store = useBlinkStore();
    expect(store.status).toBeNull();
    expect(store.isLinked).toBe(false);
  });

  it("refreshStatus loads and toggles the loading flag", async () => {
    mockedStatus.mockResolvedValue(linkedStatus);
    const store = useBlinkStore();
    const promise = store.refreshStatus();
    expect(store.loading).toBe(true);
    await promise;
    expect(store.loading).toBe(false);
    expect(store.status).toEqual(linkedStatus);
    expect(store.isLinked).toBe(true);
  });

  it("clears the loading flag even if the request fails", async () => {
    mockedStatus.mockRejectedValue(new Error("network down"));
    const store = useBlinkStore();
    await expect(store.refreshStatus()).rejects.toThrow("network down");
    expect(store.loading).toBe(false);
  });

  it("startLink refreshes status immediately when already linked", async () => {
    mockedLink.mockResolvedValue({ status: "linked", link_session_id: null });
    mockedStatus.mockResolvedValue(linkedStatus);
    const store = useBlinkStore();
    const outcome = await store.startLink("u@example.com", "pw");
    expect(outcome.status).toBe("linked");
    expect(store.isLinked).toBe(true);
  });

  it("startLink does not refresh status when 2FA is required", async () => {
    mockedLink.mockResolvedValue({
      status: "verification_required",
      link_session_id: "sess-1",
    });
    const store = useBlinkStore();
    const outcome = await store.startLink("u@example.com", "pw");
    expect(outcome.link_session_id).toBe("sess-1");
    expect(mockedStatus).not.toHaveBeenCalled();
  });

  it("completeLink verifies the code and refreshes status", async () => {
    mockedVerify.mockResolvedValue({ status: "linked", link_session_id: null });
    mockedStatus.mockResolvedValue(linkedStatus);
    const store = useBlinkStore();
    await store.completeLink("sess-1", "123456");
    expect(mockedVerify).toHaveBeenCalledWith("sess-1", "123456");
    expect(store.isLinked).toBe(true);
  });

  it("syncNow triggers a sync and refreshes status", async () => {
    mockedSync.mockResolvedValue({ status: "sync_started" });
    mockedStatus.mockResolvedValue(linkedStatus);
    const store = useBlinkStore();
    await store.syncNow();
    expect(mockedSync).toHaveBeenCalled();
    expect(store.status).toEqual(linkedStatus);
  });

  it("unlink removes the account and refreshes status", async () => {
    mockedUnlink.mockResolvedValue(undefined);
    mockedStatus.mockResolvedValue(unlinkedStatus);
    const store = useBlinkStore();
    await store.unlink();
    expect(mockedUnlink).toHaveBeenCalled();
    expect(store.isLinked).toBe(false);
  });
});
