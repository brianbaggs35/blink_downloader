import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it } from "vitest";
import { nextTick } from "vue";

import NavSidebar from "@/components/NavSidebar.vue";
import { useMobileNav } from "@/composables/useMobileNav";
import { useSidebarCollapse } from "@/composables/useSidebarCollapse";
import { makePinia, makeRouter, mountGlobal } from "./helpers";

beforeEach(() => {
  useSidebarCollapse().setCollapsed(false);
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
    expect(drawer!.querySelectorAll(".nav-item").length).toBe(10);
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
