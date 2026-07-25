import { beforeEach, describe, expect, it, vi } from "vitest";

import { authGuard } from "@/router/guards";
import { useAuthStore } from "@/stores/auth";
import { fakeUser, makePinia } from "./helpers";

import type { RouteLocationNormalizedGeneric } from "vue-router";

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  getSetupStatus: vi.fn(),
  getMe: vi.fn(),
}));

import { getMe, getSetupStatus } from "@/api";
import { ApiError } from "@/api/client";

const mockedStatus = vi.mocked(getSetupStatus);
const mockedMe = vi.mocked(getMe);

function to(name: string, fullPath = `/${name}`): RouteLocationNormalizedGeneric {
  return { name, fullPath } as RouteLocationNormalizedGeneric;
}

beforeEach(() => {
  makePinia();
  vi.clearAllMocks();
});

describe("authGuard on an uninitialized system", () => {
  beforeEach(() => {
    mockedStatus.mockResolvedValue({ initialized: false });
  });

  it("sends everything to setup", async () => {
    expect(await authGuard(to("library", "/"))).toEqual({ name: "setup" });
    expect(await authGuard(to("login"))).toEqual({ name: "setup" });
  });

  it("lets setup itself through", async () => {
    expect(await authGuard(to("setup"))).toBe(true);
  });
});

describe("authGuard when initialized but anonymous", () => {
  beforeEach(() => {
    mockedStatus.mockResolvedValue({ initialized: true });
    mockedMe.mockRejectedValue(new ApiError(401, "Unauthorized"));
  });

  it("redirects setup to login", async () => {
    expect(await authGuard(to("setup"))).toEqual({ name: "login" });
  });

  it("allows the login page", async () => {
    expect(await authGuard(to("login"))).toBe(true);
  });

  it("bounces protected routes to login with a redirect", async () => {
    expect(await authGuard(to("vehicles", "/vehicles"))).toEqual({
      name: "login",
      query: { redirect: "/vehicles" },
    });
  });
});

describe("authGuard when signed in", () => {
  beforeEach(() => {
    mockedStatus.mockResolvedValue({ initialized: true });
    mockedMe.mockResolvedValue(fakeUser);
  });

  it("keeps setup and login away", async () => {
    expect(await authGuard(to("setup"))).toEqual({ name: "library" });
    expect(await authGuard(to("login"))).toEqual({ name: "library" });
  });

  it("allows protected routes", async () => {
    expect(await authGuard(to("library", "/"))).toBe(true);
  });

  it("uses cached state on subsequent navigations", async () => {
    const store = useAuthStore();
    await authGuard(to("library", "/"));
    await authGuard(to("status"));
    expect(mockedStatus).toHaveBeenCalledTimes(1);
    expect(store.isAuthenticated).toBe(true);
  });
});
