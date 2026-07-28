import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import NavLinks from "@/components/NavLinks.vue";
import { useAuthStore } from "@/stores/auth";
import { fakeUser, makePinia, makeRouter, mountGlobal } from "./helpers";

async function mountLinks(path: string, isAdmin = true) {
  const pinia = makePinia();
  useAuthStore().user = { ...fakeUser, is_superuser: isAdmin };
  const router = makeRouter();
  await router.push(path);
  return mount(NavLinks, { global: mountGlobal(pinia, router) });
}

// Top-level destinations are real <a> links; the Settings accordion's own
// nested sections are also <a> links (so they can be deep-linked/opened in
// a new tab) but carry an extra .nav-subitem class - excluded here so these
// assertions cover just the ten top-level pages, independent of whether the
// accordion happens to be expanded (v-show keeps hidden children in the DOM).
function topLevelLinks(wrapper: VueWrapper) {
  return wrapper.findAll("a.nav-item:not(.nav-subitem)");
}

describe("NavLinks", () => {
  it("renders the ten top-level destinations in product order", async () => {
    const wrapper = await mountLinks("/");
    const labels = topLevelLinks(wrapper).map((node) => node.find("span").text());
    expect(labels).toEqual([
      "Security Feed",
      "Library",
      "Status",
      "Live View",
      "Storage",
      "Connect",
      "AI",
      "AI Usage",
      "Vehicles",
      "Biometrics",
    ]);
  });

  it("links every top-level destination to its route", async () => {
    const wrapper = await mountLinks("/");
    const hrefs = topLevelLinks(wrapper).map((node) => node.attributes("href"));
    expect(hrefs).toEqual([
      "/security-feed",
      "/",
      "/status",
      "/live",
      "/storage",
      "/integrations",
      "/ai",
      "/ai-usage",
      "/vehicles",
      "/biometrics",
    ]);
  });

  it("hides labels but keeps them accessible via title when collapsed", async () => {
    const router = makeRouter();
    await router.push("/");
    const wrapper = mount(NavLinks, {
      props: { collapsed: true },
      global: mountGlobal(makePinia(), router),
    });
    expect(wrapper.find(".nav-group-label").exists()).toBe(false);
    const firstLink = topLevelLinks(wrapper)[0]!;
    expect(firstLink.attributes("title")).toBe("Security Feed");
    expect(firstLink.find("span").attributes("style")).toContain("display: none");
  });

  it("marks only the current page's link active, not the index route on every page", async () => {
    // Library resolves to the bare "/" path, which vue-router's default
    // (non-exact) active-matching otherwise treats as an ancestor of every
    // other sibling page — these are flat top-level pages, not a nested
    // section, so exact route-name matching is used instead.
    const wrapper = await mountLinks("/status");
    const active = topLevelLinks(wrapper).filter((n) => n.classes("active"));
    expect(active.map((n) => n.find("span").text())).toEqual(["Status"]);
  });

  it("marks Library active when actually on the Library page", async () => {
    const wrapper = await mountLinks("/");
    const active = topLevelLinks(wrapper).filter((n) => n.classes("active"));
    expect(active.map((n) => n.find("span").text())).toEqual(["Library"]);
  });

  it("emits navigate when a top-level link is clicked", async () => {
    const wrapper = await mountLinks("/");
    await topLevelLinks(wrapper)[1]!.trigger("click");
    expect(wrapper.emitted("navigate")).toHaveLength(1);
  });

  it("hides Connect for a viewer, keeping Storage (which stays viewer-safe)", async () => {
    const wrapper = await mountLinks("/", false);
    const labels = topLevelLinks(wrapper).map((node) => node.find("span").text());
    expect(labels).toContain("Storage");
    expect(labels).not.toContain("Connect");
  });

  describe("Settings accordion", () => {
    // v-if, not v-show: collapsed means genuinely absent from the DOM, not
    // just hidden - otherwise every page would carry eleven invisible
    // section links, several sharing a name with a real top-level
    // destination (Vehicles, Live View, Security Feed), colliding with any
    // getByText/getByRole("link") query anywhere else in the app.
    function isExpanded(wrapper: VueWrapper): boolean {
      return wrapper.find('[data-testid="settings-accordion-children"]').exists();
    }

    it("starts collapsed away from Settings, and expanded when already there", async () => {
      const away = await mountLinks("/");
      expect(isExpanded(away)).toBe(false);

      const onSettings = await mountLinks("/settings");
      expect(isExpanded(onSettings)).toBe(true);
    });

    it("toggles open and closed on click", async () => {
      const wrapper = await mountLinks("/");
      const trigger = wrapper.find('[data-testid="settings-accordion-trigger"]');
      await trigger.trigger("click");
      expect(isExpanded(wrapper)).toBe(true);
      await trigger.trigger("click");
      expect(isExpanded(wrapper)).toBe(false);
    });

    it("lists every section for an admin, in product order", async () => {
      const wrapper = await mountLinks("/settings");
      const labels = wrapper.findAll(".nav-subitem").map((node) => node.find("span").text());
      expect(labels).toEqual([
        "General",
        "Users",
        "AI Provider",
        "Biometrics",
        "Cameras",
        "Vehicles",
        "Alerts",
        "Live View",
        "Security Feed",
        "About",
      ]);
    });

    it("hides admin-only sections for a viewer", async () => {
      const wrapper = await mountLinks("/settings", false);
      const labels = wrapper.findAll(".nav-subitem").map((node) => node.find("span").text());
      expect(labels).toEqual(["General", "About"]);
    });

    it("links each section to its own ?tab= deep link", async () => {
      const wrapper = await mountLinks("/settings");
      const hrefs = wrapper.findAll(".nav-subitem").map((node) => node.attributes("href"));
      expect(hrefs[0]).toBe("/settings?tab=general");
      expect(hrefs[1]).toBe("/settings?tab=users");
    });

    it("emits navigate when a section link is clicked", async () => {
      const wrapper = await mountLinks("/settings");
      await wrapper.findAll(".nav-subitem")[0]!.trigger("click");
      expect(wrapper.emitted("navigate")).toHaveLength(1);
    });

    it("marks the active section within the accordion", async () => {
      const wrapper = await mountLinks("/settings?tab=ai");
      const active = wrapper.findAll(".nav-subitem.active").map((n) => n.find("span").text());
      expect(active).toEqual(["AI Provider"]);
    });

    it("stays collapsed when navigating between two non-Settings pages", async () => {
      const pinia = makePinia();
      useAuthStore().user = { ...fakeUser, is_superuser: true };
      const router = makeRouter();
      await router.push("/");
      const wrapper = mount(NavLinks, { global: mountGlobal(pinia, router) });
      expect(isExpanded(wrapper)).toBe(false);

      await router.push("/status");
      await flushPromises();
      expect(isExpanded(wrapper)).toBe(false);
    });

    it("expands automatically when navigating to Settings from elsewhere", async () => {
      const pinia = makePinia();
      useAuthStore().user = { ...fakeUser, is_superuser: true };
      const router = makeRouter();
      await router.push("/");
      const wrapper = mount(NavLinks, { global: mountGlobal(pinia, router) });
      expect(isExpanded(wrapper)).toBe(false);

      await router.push("/settings?tab=users");
      await flushPromises();
      expect(isExpanded(wrapper)).toBe(true);
    });

    it("navigates directly to Settings (without expanding) when the sidebar is collapsed", async () => {
      const router = makeRouter();
      await router.push("/");
      const wrapper = mount(NavLinks, {
        props: { collapsed: true },
        global: mountGlobal(makePinia(), router),
      });
      await wrapper.find('[data-testid="settings-accordion-trigger"]').trigger("click");
      await flushPromises();
      expect(router.currentRoute.value.name).toBe("settings");
      expect(wrapper.emitted("navigate")).toHaveLength(1);
    });
  });
});
