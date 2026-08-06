import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";

import TopBar from "@/components/TopBar.vue";
import { previousRoute, recordPreviousRoute } from "@/composables/useBackNavigation";
import { useMobileNav } from "@/composables/useMobileNav";
import { useAuthStore } from "@/stores/auth";
import { fakeUser, makePinia, makeRouter, mountGlobal } from "./helpers";

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  logout: vi.fn().mockResolvedValue(undefined),
}));

import { beforeEach } from "vitest";

import { logout } from "@/api";

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(logout).mockResolvedValue(undefined);
  // Reset the module-level ref directly, not via useBackNavigation() - that
  // also calls useRouter(), which warns ("inject() can only be used inside
  // setup()") when invoked outside a component's setup(), as it would be here.
  previousRoute.value = null;
});

async function mountBar(path = "/status") {
  const pinia = makePinia();
  const store = useAuthStore();
  store.user = fakeUser;
  const router = makeRouter();
  await router.push(path);
  const wrapper = mount(TopBar, { global: mountGlobal(pinia, router) });
  return { wrapper, store, router };
}

describe("TopBar", () => {
  it("falls back to an empty title on routes without meta", async () => {
    const pinia = makePinia();
    useAuthStore().user = fakeUser;
    const bare = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: "/", component: { template: "<div />" } }],
    });
    await bare.push("/");
    const wrapper = mount(TopBar, { global: mountGlobal(pinia, bare) });
    expect(wrapper.find(".page-title").text()).toBe("");
  });

  it("shows the current page title and the user", async () => {
    const { wrapper } = await mountBar("/status");
    expect(wrapper.find(".page-title").text()).toBe("Status");
    expect(wrapper.find(".user-name").text()).toBe("Brian Baggs");
    expect(wrapper.find(".avatar").text()).toBe("BB");
  });

  it("derives initials from the email when there is no display name", async () => {
    const { wrapper, store } = await mountBar();
    store.user = { ...fakeUser, display_name: "" };
    await flushPromises();
    expect(wrapper.find(".avatar").text()).toBe("AE");
  });

  it("toggles the theme", async () => {
    document.documentElement.classList.add("blink-dark");
    const { wrapper } = await mountBar();
    await wrapper.find('[data-testid="theme-toggle"]').trigger("click");
    expect(document.documentElement.classList.contains("blink-dark")).toBe(false);
  });

  it("signs out and navigates to login", async () => {
    const { wrapper, store, router } = await mountBar();
    await wrapper.find('[data-testid="sign-out"]').trigger("click");
    await flushPromises();
    expect(store.user).toBeNull();
    expect(router.currentRoute.value.name).toBe("login");
  });

  it("opens the mobile nav drawer from the menu toggle", async () => {
    useMobileNav().close();
    const { wrapper } = await mountBar();
    await wrapper.find('[data-testid="mobile-nav-toggle"]').trigger("click");
    expect(useMobileNav().isOpen.value).toBe(true);
    useMobileNav().close();
  });

  describe("back button", () => {
    it("stays hidden on a non-Settings route even with a previous route recorded", async () => {
      recordPreviousRoute(
        { name: "settings", matched: [{}] } as never,
        { name: "vehicles", matched: [{}] } as never,
      );
      const { wrapper } = await mountBar("/status");
      expect(wrapper.find('[data-testid="topbar-back"]').exists()).toBe(false);
    });

    it("stays hidden on Settings when there's no previous route to return to", async () => {
      const { wrapper } = await mountBar("/settings");
      expect(wrapper.find('[data-testid="topbar-back"]').exists()).toBe(false);
    });

    it("shows on Settings once a previous route is recorded, and navigates back to it", async () => {
      recordPreviousRoute(
        { name: "settings", matched: [{}] } as never,
        { name: "vehicles", matched: [{}] } as never,
      );
      const { wrapper, router } = await mountBar("/settings");
      const back = wrapper.find('[data-testid="topbar-back"]');
      expect(back.exists()).toBe(true);
      await back.trigger("click");
      await flushPromises();
      expect(router.currentRoute.value.name).toBe("vehicles");
    });
  });
});
