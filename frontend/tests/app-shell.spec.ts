import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  getBlinkStatus: vi.fn(),
}));

import { getBlinkStatus } from "@/api";
import App from "@/App.vue";
import AppLogo from "@/components/AppLogo.vue";
import NavSidebar from "@/components/NavSidebar.vue";
import PageHeader from "@/components/PageHeader.vue";
import TopBar from "@/components/TopBar.vue";
import { useAuthStore } from "@/stores/auth";
import LibraryView from "@/views/LibraryView.vue";
import { fakeUser, makePinia, makeRouter, mountGlobal } from "./helpers";

const mockedStatus = vi.mocked(getBlinkStatus);

beforeEach(() => {
  vi.clearAllMocks();
  mockedStatus.mockResolvedValue({
    linked: false,
    status: null,
    last_sync: null,
    last_error: null,
    camera_count: 0,
  });
});

describe("application shell", () => {
  it("renders sidebar, topbar, and the routed view", async () => {
    const pinia = makePinia();
    useAuthStore().user = fakeUser;
    const router = makeRouter();
    await router.push("/");
    const wrapper = mount(App, { global: mountGlobal(pinia, router) });
    await flushPromises();
    expect(wrapper.findComponent(NavSidebar).exists()).toBe(true);
    expect(wrapper.findComponent(TopBar).exists()).toBe(true);
    expect(wrapper.findComponent(LibraryView).exists()).toBe(true);
  });

  it("renders the logo with its default size", () => {
    const wrapper = mount(AppLogo);
    expect(wrapper.find("svg").attributes("width")).toBe("32");
  });

  it("renders PageHeader without a description", () => {
    const wrapper = mount(PageHeader, { props: { title: "Bare" } });
    expect(wrapper.find(".title").text()).toBe("Bare");
    expect(wrapper.find(".description").exists()).toBe(false);
  });
});
