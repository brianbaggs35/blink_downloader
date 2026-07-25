import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import LibraryView from "@/views/LibraryView.vue";
import { makePinia, makeRouter, mountGlobal } from "./helpers";

describe("LibraryView", () => {
  it("offers a path to settings from the empty state", async () => {
    const router = makeRouter();
    await router.push("/");
    const wrapper = mount(LibraryView, { global: mountGlobal(makePinia(), router) });
    expect(wrapper.find(".title").text()).toBe("Library");
    await wrapper.find('[data-testid="go-settings"]').trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.name).toBe("settings");
  });
});
