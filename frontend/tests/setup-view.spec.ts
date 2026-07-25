import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/client";
import SetupView from "@/views/SetupView.vue";
import { fakeUser, makePinia, makeRouter, mountGlobal } from "./helpers";

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  runSetup: vi.fn(),
  login: vi.fn(),
  getMe: vi.fn(),
}));

import { beforeEach } from "vitest";

import { getMe, login, runSetup } from "@/api";

const mockedSetup = vi.mocked(runSetup);
const mockedLogin = vi.mocked(login);
const mockedMe = vi.mocked(getMe);

beforeEach(() => {
  vi.clearAllMocks();
});

async function mountSetup() {
  const router = makeRouter();
  await router.push("/setup");
  const wrapper = mount(SetupView, { global: mountGlobal(makePinia(), router) });
  return { wrapper, router };
}

async function fill(
  wrapper: Awaited<ReturnType<typeof mountSetup>>["wrapper"],
  password: string,
  confirm: string,
) {
  await wrapper.find('[data-testid="display-name"]').setValue("Brian");
  await wrapper.find('[data-testid="email"]').setValue("admin@example.com");
  await wrapper.find('[data-testid="password"] input').setValue(password);
  await wrapper.find('[data-testid="confirm"] input').setValue(confirm);
  await wrapper.find("form").trigger("submit");
  await flushPromises();
}

describe("SetupView", () => {
  it("rejects short passwords client-side", async () => {
    const { wrapper } = await mountSetup();
    await fill(wrapper, "short", "short");
    expect(wrapper.find('[data-testid="setup-error"]').text()).toContain("at least 12");
    expect(mockedSetup).not.toHaveBeenCalled();
  });

  it("rejects mismatched passwords client-side", async () => {
    const { wrapper } = await mountSetup();
    await fill(wrapper, "a-long-enough-password", "a-different-password");
    expect(wrapper.find('[data-testid="setup-error"]').text()).toBe("Passwords do not match.");
    expect(mockedSetup).not.toHaveBeenCalled();
  });

  it("creates the admin, signs in, and lands on the library", async () => {
    mockedSetup.mockResolvedValue(fakeUser);
    mockedLogin.mockResolvedValue(undefined);
    mockedMe.mockResolvedValue(fakeUser);
    const { wrapper, router } = await mountSetup();
    await fill(wrapper, "a-long-enough-password", "a-long-enough-password");
    expect(mockedSetup).toHaveBeenCalledWith({
      email: "admin@example.com",
      password: "a-long-enough-password",
      display_name: "Brian",
    });
    expect(router.currentRoute.value.name).toBe("library");
  });

  it("surfaces API errors verbatim", async () => {
    mockedSetup.mockRejectedValue(new ApiError(409, "Setup has already been completed."));
    const { wrapper } = await mountSetup();
    await fill(wrapper, "a-long-enough-password", "a-long-enough-password");
    expect(wrapper.find('[data-testid="setup-error"]').text()).toBe(
      "Setup has already been completed.",
    );
  });

  it("falls back to a generic failure message", async () => {
    mockedSetup.mockRejectedValue(new TypeError("fetch failed"));
    const { wrapper } = await mountSetup();
    await fill(wrapper, "a-long-enough-password", "a-long-enough-password");
    expect(wrapper.find('[data-testid="setup-error"]').text()).toContain("Setup failed");
  });
});
