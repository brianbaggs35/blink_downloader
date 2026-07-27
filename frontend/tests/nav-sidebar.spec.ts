import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";

import NavSidebar from "@/components/NavSidebar.vue";
import { useMobileNav } from "@/composables/useMobileNav";
import { useSidebarCollapse } from "@/composables/useSidebarCollapse";
import { fakeBlinkStatus, makePinia, makeRouter, mountGlobal } from "./helpers";

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  getBlinkStatus: vi.fn(),
}));

import { getBlinkStatus } from "@/api";

const mockedBlinkStatus = vi.mocked(getBlinkStatus);

const unlinkedStatus = fakeBlinkStatus();

beforeEach(() => {
  useSidebarCollapse().setCollapsed(false);
  vi.clearAllMocks();
  mockedBlinkStatus.mockResolvedValue(unlinkedStatus);
});

async function mountSidebar() {
  const router = makeRouter();
  await router.push("/");
  const wrapper = mount(NavSidebar, {
    global: mountGlobal(makePinia(), router),
    attachTo: document.body,
  });
  return wrapper;
}

describe("NavSidebar", () => {
  it("renders the destinations in the static desktop sidebar", async () => {
    const wrapper = await mountSidebar();
    const labels = wrapper.findAll(".sidebar .nav-item span").map((node) => node.text());
    expect(labels).toContain("Library");
    expect(labels).toContain("Settings");
  });

  it("shows the app version in the desktop footer", async () => {
    const wrapper = await mountSidebar();
    expect(wrapper.find(".sidebar .version").text()).toBe(`v${__APP_VERSION__}`);
  });

  it("keeps the mobile drawer closed by default", async () => {
    useMobileNav().close();
    await mountSidebar();
    expect(document.body.querySelector('[data-testid="mobile-nav-drawer"] .nav')).toBeFalsy();
  });

  it("opens the mobile drawer, with the same nav and footer, when useMobileNav().open() is called", async () => {
    useMobileNav().close();
    await mountSidebar();
    useMobileNav().open();
    await nextTick();

    const drawer = document.body.querySelector('[data-testid="mobile-nav-drawer"]');
    expect(drawer).toBeTruthy();
    expect(drawer!.querySelectorAll(".nav-item").length).toBe(11);
    expect(drawer!.textContent).toContain(`v${__APP_VERSION__}`);
    useMobileNav().close();
  });

  it("stays in sync when the drawer is dismissed directly (escape/mask click)", async () => {
    useMobileNav().open();
    const wrapper = await mountSidebar();
    await nextTick();

    await wrapper.findComponent({ name: "Drawer" }).vm.$emit("update:visible", false);
    expect(useMobileNav().isOpen.value).toBe(false);
  });

  it("closes the drawer when its brand link is clicked", async () => {
    useMobileNav().open();
    await mountSidebar();
    await nextTick();

    document.body.querySelector<HTMLElement>('[data-testid="mobile-nav-drawer"] .brand')!.click();
    await nextTick();
    expect(useMobileNav().isOpen.value).toBe(false);
  });

  it("closes the drawer when a nav link inside it is clicked", async () => {
    useMobileNav().open();
    const wrapper = await mountSidebar();
    await nextTick();

    const link = document
      .querySelector('[data-testid="mobile-nav-drawer"]')!
      .querySelectorAll<HTMLElement>(".nav-item")[1]!;
    link.click();
    await flushPromises();
    expect(useMobileNav().isOpen.value).toBe(false);
    wrapper.unmount();
  });

  it("collapses and expands the desktop sidebar, persisting the choice", async () => {
    const wrapper = await mountSidebar();
    const toggle = wrapper.find('[data-testid="sidebar-collapse-toggle"]');

    expect(wrapper.find(".sidebar").classes()).not.toContain("collapsed");
    await toggle.trigger("click");
    expect(wrapper.find(".sidebar").classes()).toContain("collapsed");
    expect(localStorage.getItem("blink-sidebar-collapsed")).toBe("true");
    expect(wrapper.find(".brand-text").isVisible()).toBe(false);

    await toggle.trigger("click");
    expect(wrapper.find(".sidebar").classes()).not.toContain("collapsed");
    expect(localStorage.getItem("blink-sidebar-collapsed")).toBe("false");
  });
});

describe("NavSidebar Blink connection badge", () => {
  it("shows 'Blink not connected' when no account is linked", async () => {
    const wrapper = await mountSidebar();
    await flushPromises();
    const badge = wrapper.find('[data-testid="nav-blink-badge"]');
    expect(badge.classes()).toContain("badge-unlinked");
    expect(badge.text()).toBe("Blink not connected");
  });

  it("shows 'Blink connected' for an active account", async () => {
    mockedBlinkStatus.mockResolvedValue({ ...unlinkedStatus, linked: true, status: "active" });
    const wrapper = await mountSidebar();
    await flushPromises();
    const badge = wrapper.find('[data-testid="nav-blink-badge"]');
    expect(badge.classes()).toContain("badge-connected");
    expect(badge.text()).toBe("Blink connected");
  });

  it("shows 'Blink needs attention' for a linked account in an error state", async () => {
    mockedBlinkStatus.mockResolvedValue({ ...unlinkedStatus, linked: true, status: "error" });
    const wrapper = await mountSidebar();
    await flushPromises();
    const badge = wrapper.find('[data-testid="nav-blink-badge"]');
    expect(badge.classes()).toContain("badge-attention");
    expect(badge.text()).toBe("Blink needs attention");
  });

  it("falls back to the unlinked badge if the status check fails", async () => {
    mockedBlinkStatus.mockRejectedValue(new TypeError("network down"));
    const wrapper = await mountSidebar();
    await flushPromises();
    expect(wrapper.find('[data-testid="nav-blink-badge"]').classes()).toContain("badge-unlinked");
  });

  it("hides the badge label but keeps the dot when the sidebar is collapsed", async () => {
    const wrapper = await mountSidebar();
    await flushPromises();
    await wrapper.find('[data-testid="sidebar-collapse-toggle"]').trigger("click");
    const badge = wrapper.find('[data-testid="nav-blink-badge"]');
    expect(badge.find(".badge-dot").exists()).toBe(true);
    expect(badge.find(".badge-label").isVisible()).toBe(false);
  });

  it("shows the same badge in the mobile drawer", async () => {
    mockedBlinkStatus.mockResolvedValue({ ...unlinkedStatus, linked: true, status: "active" });
    useMobileNav().close();
    const wrapper = await mountSidebar();
    useMobileNav().open();
    await nextTick();
    await flushPromises();
    // Teleported drawer content isn't in this wrapper's own vnode tree, and
    // earlier tests in this file leave their own (unmounted-but-undetached)
    // drawers behind in document.body - the freshly teleported one is always
    // the last match, never the first.
    const badges = document.body.querySelectorAll('[data-testid="nav-blink-badge-mobile"]');
    expect(badges[badges.length - 1]?.textContent).toBe("Blink connected");
    useMobileNav().close();
    wrapper.unmount();
  });

  it("polls for status updates and stops polling once unmounted", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    try {
      const wrapper = await mountSidebar();
      await flushPromises();
      expect(mockedBlinkStatus).toHaveBeenCalledTimes(1);

      await vi.advanceTimersByTimeAsync(60_000);
      expect(mockedBlinkStatus).toHaveBeenCalledTimes(2);

      wrapper.unmount();
      await vi.advanceTimersByTimeAsync(120_000);
      expect(mockedBlinkStatus).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });
});
