import { Icon } from "@iconify/vue";
import { mount } from "@vue/test-utils";
import Tag from "primevue/tag";
import { describe, expect, it } from "vitest";

import BatteryIndicator from "@/components/BatteryIndicator.vue";
import { makePinia, mountGlobal } from "./helpers";

function mountIndicator(battery: string | null | undefined) {
  return mount(BatteryIndicator, {
    props: { battery },
    global: mountGlobal(makePinia()),
  });
}

describe("BatteryIndicator", () => {
  it("renders an OK / success state", () => {
    const wrapper = mountIndicator("ok");
    expect(wrapper.findComponent(Tag).props("severity")).toBe("success");
    expect(wrapper.findComponent(Tag).props("value")).toBe("OK");
    expect(wrapper.findComponent(Icon).props("icon")).toBe("mdi:battery");
  });

  it("renders a Low / danger state", () => {
    const wrapper = mountIndicator("low");
    expect(wrapper.findComponent(Tag).props("severity")).toBe("danger");
    expect(wrapper.findComponent(Tag).props("value")).toBe("Low");
    expect(wrapper.findComponent(Icon).props("icon")).toBe("mdi:battery-alert");
  });

  it("matches ok/low case-insensitively", () => {
    expect(mountIndicator("OK").findComponent(Tag).props("value")).toBe("OK");
    expect(mountIndicator("Low").findComponent(Tag).props("value")).toBe("Low");
  });

  it("renders a No data / secondary state for null", () => {
    const wrapper = mountIndicator(null);
    expect(wrapper.findComponent(Tag).props("severity")).toBe("secondary");
    expect(wrapper.findComponent(Tag).props("value")).toBe("No data");
    expect(wrapper.findComponent(Icon).props("icon")).toBe("mdi:battery-unknown");
  });

  it("renders a No data / secondary state for an unrecognized value rather than guessing", () => {
    const wrapper = mountIndicator("charging");
    expect(wrapper.findComponent(Tag).props("severity")).toBe("secondary");
    expect(wrapper.findComponent(Tag).props("value")).toBe("No data");
  });
});
