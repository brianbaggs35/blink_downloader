import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/client";
import { useAuthStore } from "@/stores/auth";
import { fakeUser, makePinia } from "./helpers";

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  getSetupStatus: vi.fn(),
  getMe: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
  runSetup: vi.fn(),
}));

import { getMe, getSetupStatus, login, logout, runSetup } from "@/api";

const mockedStatus = vi.mocked(getSetupStatus);
const mockedMe = vi.mocked(getMe);
const mockedLogin = vi.mocked(login);
const mockedLogout = vi.mocked(logout);
const mockedSetup = vi.mocked(runSetup);

beforeEach(() => {
  makePinia();
  vi.clearAllMocks();
});

describe("auth store bootstrap", () => {
  it("records an uninitialized system without probing the session", async () => {
    mockedStatus.mockResolvedValue({ initialized: false });
    const store = useAuthStore();
    await store.bootstrap();
    expect(store.initialized).toBe(false);
    expect(mockedMe).not.toHaveBeenCalled();
  });

  it("loads the current user when a session exists", async () => {
    mockedStatus.mockResolvedValue({ initialized: true });
    mockedMe.mockResolvedValue(fakeUser);
    const store = useAuthStore();
    await store.bootstrap();
    expect(store.user).toEqual(fakeUser);
    expect(store.isAuthenticated).toBe(true);
  });

  it("treats a 401 probe as anonymous", async () => {
    mockedStatus.mockResolvedValue({ initialized: true });
    mockedMe.mockRejectedValue(new ApiError(401, "Unauthorized"));
    const store = useAuthStore();
    await store.bootstrap();
    expect(store.user).toBeNull();
    expect(store.isAuthenticated).toBe(false);
  });

  it("rethrows unexpected probe failures", async () => {
    mockedStatus.mockResolvedValue({ initialized: true });
    mockedMe.mockRejectedValue(new ApiError(500, "boom"));
    const store = useAuthStore();
    await expect(store.bootstrap()).rejects.toThrow("boom");
  });

  it("rethrows non-ApiError probe failures", async () => {
    mockedStatus.mockResolvedValue({ initialized: true });
    mockedMe.mockRejectedValue(new TypeError("network down"));
    const store = useAuthStore();
    await expect(store.bootstrap()).rejects.toThrow("network down");
  });

  it("only fetches status and probes once", async () => {
    mockedStatus.mockResolvedValue({ initialized: true });
    mockedMe.mockRejectedValue(new ApiError(401, "Unauthorized"));
    const store = useAuthStore();
    await store.bootstrap();
    await store.bootstrap();
    expect(mockedStatus).toHaveBeenCalledTimes(1);
    expect(mockedMe).toHaveBeenCalledTimes(1);
  });
});

describe("auth store actions", () => {
  it("login stores the profile", async () => {
    mockedLogin.mockResolvedValue(undefined);
    mockedMe.mockResolvedValue(fakeUser);
    const store = useAuthStore();
    await store.login("admin@example.com", "pw");
    expect(mockedLogin).toHaveBeenCalledWith("admin@example.com", "pw");
    expect(store.user).toEqual(fakeUser);
  });

  it("logout clears the profile", async () => {
    mockedLogout.mockResolvedValue(undefined);
    const store = useAuthStore();
    store.user = fakeUser;
    await store.logout();
    expect(store.user).toBeNull();
  });

  it("completeSetup registers then signs in", async () => {
    mockedSetup.mockResolvedValue(fakeUser);
    mockedLogin.mockResolvedValue(undefined);
    mockedMe.mockResolvedValue(fakeUser);
    const store = useAuthStore();
    await store.completeSetup({
      email: "admin@example.com",
      password: "p".repeat(12),
      display_name: "Brian",
    });
    expect(mockedSetup).toHaveBeenCalled();
    expect(store.initialized).toBe(true);
    expect(store.user).toEqual(fakeUser);
  });

  it("displayName prefers the display name and falls back to email", () => {
    const store = useAuthStore();
    expect(store.displayName).toBe("");
    store.user = { ...fakeUser, display_name: "" };
    expect(store.displayName).toBe("admin@example.com");
    store.user = fakeUser;
    expect(store.displayName).toBe("Brian Baggs");
  });

  it("isAdmin reflects the signed-in user's is_superuser flag", () => {
    const store = useAuthStore();
    expect(store.isAdmin).toBe(false);
    store.user = { ...fakeUser, is_superuser: false };
    expect(store.isAdmin).toBe(false);
    store.user = { ...fakeUser, is_superuser: true };
    expect(store.isAdmin).toBe(true);
  });
});
