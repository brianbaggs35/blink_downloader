import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import SettingsAboutPanel from "@/components/SettingsAboutPanel.vue";

describe("SettingsAboutPanel", () => {
  it("links to the project's GitHub repo", () => {
    const wrapper = mount(SettingsAboutPanel);
    const link = wrapper.find('[data-testid="about-repo-link"]');
    expect(link.attributes("href")).toBe("https://github.com/brianbaggs35/blink_downloader");
    expect(link.attributes("target")).toBe("_blank");
    expect(link.attributes("rel")).toContain("noopener");
  });

  it("credits blinkpy", () => {
    const wrapper = mount(SettingsAboutPanel);
    const link = wrapper.find('[data-testid="about-blinkpy-link"]');
    expect(link.attributes("href")).toBe("https://github.com/fronzbot/blinkpy");
    expect(wrapper.text()).toContain("blinkpy");
  });

  it("lists the technologies the project is built with", () => {
    const wrapper = mount(SettingsAboutPanel);
    expect(wrapper.text()).toContain("FastAPI");
    expect(wrapper.text()).toContain("Vue.js");
    expect(wrapper.text()).toContain("PrimeVue");
    expect(wrapper.text()).toContain("insightface");
  });
});
