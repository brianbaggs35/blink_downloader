import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import LiveView from "@/views/LiveView.vue";
import StorageView from "@/views/StorageView.vue";
import { makePinia, mountGlobal } from "./helpers";

const cases = [
  { component: LiveView, title: "Live View", icon: "pi-video" },
  { component: StorageView, title: "Storage", icon: "pi-database" },
] as const;

describe("placeholder views", () => {
  it.each(cases)("renders $title with its empty state", ({ component, title, icon }) => {
    const wrapper = mount(component, { global: mountGlobal(makePinia()) });
    expect(wrapper.find(".title").text()).toBe(title);
    expect(wrapper.find(`.icon-ring i.${icon}`).exists()).toBe(true);
    expect(wrapper.find(".empty-description").text().length).toBeGreaterThan(20);
  });
});
