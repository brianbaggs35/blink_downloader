import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/client";
import LoginView from "@/views/LoginView.vue";
import { fakeUser, makePinia, makeRouter, mountGlobal } from "./helpers";

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  login: vi.fn(),
  getMe: vi.fn(),
}));

import { beforeEach } from "vitest";

import { getMe, login } from "@/api";

const mockedLogin = vi.mocked(login);
const mockedMe = vi.mocked(getMe);

beforeEach(() => {
  vi.clearAllMocks();
});

async function mountLogin(path = "/login") {
  const router = makeRouter();
  await router.push(path);
  const wrapper = mount(LoginView, { global: mountGlobal(makePinia(), router) });
  return { wrapper, router };
}

async function submit(wrapper: Awaited<ReturnType<typeof mountLogin>>["wrapper"]) {
  await wrapper.find('[data-testid="email"]').setValue("admin@example.com");
  await wrapper.find('[data-testid="password"] input').setValue("correct-horse-battery");
  await wrapper.find("form").trigger("submit");
  await flushPromises();
}

describe("LoginView", () => {
  it("signs in and lands on the library", async () => {
    mockedLogin.mockResolvedValue(undefined);
    mockedMe.mockResolvedValue(fakeUser);
    const { wrapper, router } = await mountLogin();
    await submit(wrapper);
    expect(mockedLogin).toHaveBeenCalledWith("admin@example.com", "correct-horse-battery");
    expect(router.currentRoute.value.name).toBe("library");
  });

  it("lands on Security Feed when that's the user's preference", async () => {
    mockedLogin.mockResolvedValue(undefined);
    mockedMe.mockResolvedValue({ ...fakeUser, default_landing_page: "security_feed" });
    const { wrapper, router } = await mountLogin();
    await submit(wrapper);
    expect(router.currentRoute.value.name).toBe("security-feed");
  });

  it("honors a redirect query", async () => {
    mockedLogin.mockResolvedValue(undefined);
    mockedMe.mockResolvedValue(fakeUser);
    const { wrapper, router } = await mountLogin("/login?redirect=/vehicles");
    await submit(wrapper);
    expect(router.currentRoute.value.fullPath).toBe("/vehicles");
  });

  it("explains a rejected password", async () => {
    mockedLogin.mockRejectedValue(new ApiError(400, "LOGIN_BAD_CREDENTIALS"));
    const { wrapper } = await mountLogin();
    await submit(wrapper);
    expect(wrapper.find('[data-testid="login-error"]').text()).toBe(
      "Incorrect email or password.",
    );
  });

  it("shows a generic message for other failures", async () => {
    mockedLogin.mockRejectedValue(new TypeError("fetch failed"));
    const { wrapper } = await mountLogin();
    await submit(wrapper);
    expect(wrapper.find('[data-testid="login-error"]').text()).toContain("Sign-in failed");
  });
});
