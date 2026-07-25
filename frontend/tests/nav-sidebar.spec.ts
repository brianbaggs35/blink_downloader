import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import NavSidebar from "@/components/NavSidebar.vue";
import { makePinia, makeRouter, mountGlobal } from "./helpers";

describe("NavSidebar", () => {
  it("renders the nine destinations in product order", async () => {
    const router = makeRouter();
    await router.push("/");
    const wrapper = mount(NavSidebar, { global: mountGlobal(makePinia(), router) });
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
    const router = makeRouter();
    await router.push("/");
    const wrapper = mount(NavSidebar, { global: mountGlobal(makePinia(), router) });
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

  it("shows the app version in the footer", async () => {
    const router = makeRouter();
    await router.push("/");
    const wrapper = mount(NavSidebar, { global: mountGlobal(makePinia(), router) });
    expect(wrapper.find(".version").text()).toBe(`v${__APP_VERSION__}`);
  });
});
