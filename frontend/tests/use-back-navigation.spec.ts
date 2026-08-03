import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("vue-router", async (importOriginal) => ({
  ...(await importOriginal<typeof import("vue-router")>()),
  useRouter: vi.fn(),
}));

import { useRouter } from "vue-router";

import { recordPreviousRoute, useBackNavigation } from "@/composables/useBackNavigation";

import type { RouteLocationNormalizedLoaded } from "vue-router";

function routeFor(name: string, matched: unknown[] = [{}]): RouteLocationNormalizedLoaded {
  return { name, matched } as unknown as RouteLocationNormalizedLoaded;
}

const mockedUseRouter = vi.mocked(useRouter);

beforeEach(() => {
  useBackNavigation().previousRoute.value = null;
  vi.clearAllMocks();
});

describe("recordPreviousRoute", () => {
  it("ignores the app's very first navigation, which has no matched route", () => {
    recordPreviousRoute(routeFor("settings"), routeFor("login", []));
    expect(useBackNavigation().previousRoute.value).toBeNull();
  });

  it("ignores a navigation that only changes the current route's query (e.g. switching Settings tabs)", () => {
    recordPreviousRoute(routeFor("settings"), routeFor("security-feed"));
    const { previousRoute } = useBackNavigation();
    expect(previousRoute.value?.name).toBe("security-feed");

    recordPreviousRoute(routeFor("settings"), routeFor("settings"));
    expect(previousRoute.value?.name).toBe("security-feed");
  });

  it("records a genuine change of route", () => {
    recordPreviousRoute(routeFor("settings"), routeFor("vehicles"));
    expect(useBackNavigation().previousRoute.value?.name).toBe("vehicles");
  });
});

describe("useBackNavigation goBack", () => {
  it("pushes to the recorded previous route", () => {
    const push = vi.fn();
    mockedUseRouter.mockReturnValue({ push } as unknown as ReturnType<typeof useRouter>);
    recordPreviousRoute(routeFor("settings"), routeFor("vehicles"));

    useBackNavigation().goBack();

    expect(push).toHaveBeenCalledWith(expect.objectContaining({ name: "vehicles" }));
  });

  it("does nothing when there is no previous route to go back to", () => {
    const push = vi.fn();
    mockedUseRouter.mockReturnValue({ push } as unknown as ReturnType<typeof useRouter>);

    useBackNavigation().goBack();

    expect(push).not.toHaveBeenCalled();
  });
});
