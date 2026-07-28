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

  it("attributes the storage-integration trademarks to their owners", () => {
    const wrapper = mount(SettingsAboutPanel);
    expect(wrapper.text()).toContain("Google Drive is a trademark of Google LLC");
    expect(wrapper.text()).toContain("Microsoft OneDrive is a trademark of Microsoft Corporation");
    expect(wrapper.text()).toContain(
      "Amazon S3 is a trademark of Amazon.com, Inc. or its affiliates",
    );
    expect(wrapper.text()).toContain("not affiliated with, endorsed by, or sponsored by");
  });

  it("credits the source of the Google Drive and OneDrive icons", () => {
    const wrapper = mount(SettingsAboutPanel);
    const link = wrapper.find('a[href="https://github.com/Templarian/MaterialDesign"]');
    expect(link.exists()).toBe(true);
    expect(link.text()).toBe("Pictogrammers Material Design Icons");
    expect(wrapper.text()).toContain("not to imply endorsement");
  });
});
