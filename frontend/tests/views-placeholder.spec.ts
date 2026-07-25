import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import AiUsageView from "@/views/AiUsageView.vue";
import AiView from "@/views/AiView.vue";
import BiometricsView from "@/views/BiometricsView.vue";
import LiveView from "@/views/LiveView.vue";
import StorageView from "@/views/StorageView.vue";
import VehiclesView from "@/views/VehiclesView.vue";
import { makePinia, mountGlobal } from "./helpers";

const cases = [
  { component: LiveView, title: "Live View", icon: "pi-video" },
  { component: StorageView, title: "Storage", icon: "pi-database" },
  { component: AiView, title: "AI", icon: "pi-sparkles" },
  { component: AiUsageView, title: "AI Usage", icon: "pi-chart-bar" },
  { component: VehiclesView, title: "Vehicles", icon: "pi-car" },
  { component: BiometricsView, title: "Biometrics", icon: "pi-id-card" },
] as const;

describe("placeholder views", () => {
  it.each(cases)("renders $title with its empty state", ({ component, title, icon }) => {
    const wrapper = mount(component, { global: mountGlobal(makePinia()) });
    expect(wrapper.find(".title").text()).toBe(title);
    expect(wrapper.find(`.icon-ring i.${icon}`).exists()).toBe(true);
    expect(wrapper.find(".empty-description").text().length).toBeGreaterThan(20);
  });
});
