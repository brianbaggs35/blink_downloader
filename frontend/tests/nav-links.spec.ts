import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import NavLinks from "@/components/NavLinks.vue";
import { makePinia, makeRouter, mountGlobal } from "./helpers";

async function mountLinks(path: string) {
  const router = makeRouter();
  await router.push(path);
  const wrapper = mount(NavLinks, { global: mountGlobal(makePinia(), router) });
  return wrapper;
}

describe("NavLinks", () => {
  it("renders the nine destinations in product order", async () => {
    const wrapper = await mountLinks("/");
    const labels = wrapper.findAll(".nav-item span").map((node) => node.text());
    expect(labels).toEqual([
      "Library",
      "Status",
      "Live View",
      "Storage",
      "AI",
      "AI Usage",
      "Vehicles",
      "Biometrics",
      "Settings",
    ]);
  });

  it("links every destination to its route", async () => {
    const wrapper = await mountLinks("/");
    const hrefs = wrapper.findAll("a.nav-item").map((node) => node.attributes("href"));
    expect(hrefs).toEqual([
      "/",
      "/status",
      "/live",
      "/storage",
      "/ai",
      "/ai-usage",
      "/vehicles",
      "/biometrics",
      "/settings",
    ]);
  });

  it("marks only the current page's link active, not the index route on every page", async () => {
    // Library resolves to the bare "/" path, which vue-router's default
    // (non-exact) active-matching otherwise treats as an ancestor of every
    // other sibling page — these are flat top-level pages, not a nested
    // section, so exact route-name matching is used instead.
    const wrapper = await mountLinks("/settings");
    const active = wrapper.findAll(".nav-item.active span").map((n) => n.text());
    expect(active).toEqual(["Settings"]);
  });

  it("marks Library active when actually on the Library page", async () => {
    const wrapper = await mountLinks("/");
    const active = wrapper.findAll(".nav-item.active span").map((n) => n.text());
    expect(active).toEqual(["Library"]);
  });

  it("emits navigate when a link is clicked", async () => {
    const wrapper = await mountLinks("/");
    await wrapper.findAll("a.nav-item")[1]!.trigger("click");
    expect(wrapper.emitted("navigate")).toHaveLength(1);
  });
});
