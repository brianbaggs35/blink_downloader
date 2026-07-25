import { mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";

vi.mock("video.js", () => ({
  default: vi.fn(() => ({ dispose: vi.fn(), src: vi.fn() })),
}));
vi.mock("video.js/dist/video-js.css", () => ({}));

import ClipDetailModal from "@/components/ClipDetailModal.vue";
import VideoPlayer from "@/components/VideoPlayer.vue";
import { makePinia, mountGlobal } from "./helpers";

import type { ClipRead } from "@/api";

const clip: ClipRead = {
  id: "clip-1",
  camera_id: "cam-1",
  recorded_at: "2026-07-20T18:30:00Z",
  duration_seconds: 65,
  file_size_bytes: 2048,
  downloaded_at: "2026-07-20T18:31:00Z",
  deleted_on_blink: false,
  thumbnail_generated: true,
};

// PrimeVue's Dialog teleports its content to document.body by default, one
// tick after mount (an overlay-positioning step) — query the real document
// after a nextTick rather than stubbing Teleport (which renders an empty
// placeholder with no content at all). Hard-reset the body between tests
// since the exit transition (stubbed by VTU, but still async) doesn't
// guarantee synchronous DOM removal on unmount.
async function mountModal(clipProp: ClipRead | null) {
  const wrapper = mount(ClipDetailModal, {
    props: { clip: clipProp, cameraName: "Front Door" },
    global: mountGlobal(makePinia()),
    attachTo: document.body,
  });
  await nextTick();
  return wrapper;
}

afterEach(() => {
  document.body.innerHTML = "";
});

describe("ClipDetailModal", () => {
  it("is not visible when clip is null", async () => {
    const wrapper = await mountModal(null);
    expect(wrapper.findComponent({ name: "Dialog" }).props("visible")).toBe(false);
  });

  it("shows the player and metadata for a downloaded clip", async () => {
    const wrapper = await mountModal(clip);
    expect(wrapper.findComponent(VideoPlayer).exists()).toBe(true);
    expect(wrapper.findComponent(VideoPlayer).props("src")).toBe("/api/clips/clip-1/stream");
    expect(document.body.textContent).toContain("1:05");
    expect(document.body.textContent).toContain("2.0 KB");
  });

  it("shows a not-ready message instead of the player when undownloaded", async () => {
    const wrapper = await mountModal({ ...clip, downloaded_at: null });
    expect(wrapper.findComponent(VideoPlayer).exists()).toBe(false);
    expect(document.body.textContent).toContain("hasn't finished downloading");
  });

  it("shows the AI-not-enabled placeholder rather than fake data", async () => {
    await mountModal(clip);
    expect(document.body.textContent).toContain("AI analysis isn't enabled yet");
  });

  it("renders a download link for a downloaded clip", async () => {
    await mountModal(clip);
    const link = document.body.querySelector('[data-testid="modal-download"]');
    expect(link?.getAttribute("href")).toBe("/api/clips/clip-1/download");
  });

  it("omits the download link when the clip isn't downloaded", async () => {
    await mountModal({ ...clip, downloaded_at: null });
    expect(document.body.querySelector('[data-testid="modal-download"]')).toBeNull();
  });

  it("emits delete when the delete button is clicked", async () => {
    const wrapper = await mountModal(clip);
    const button = document.body.querySelector<HTMLElement>('[data-testid="modal-delete"]');
    button?.click();
    await nextTick();
    expect(wrapper.emitted("delete")).toHaveLength(1);
  });

  it("emits close when the dialog's visible model turns false", async () => {
    const wrapper = await mountModal(clip);
    await wrapper.findComponent({ name: "Dialog" }).vm.$emit("update:visible", false);
    expect(wrapper.emitted("close")).toHaveLength(1);
  });

  it("does not emit close when the dialog's visible model turns true", async () => {
    const wrapper = await mountModal(clip);
    await wrapper.findComponent({ name: "Dialog" }).vm.$emit("update:visible", true);
    expect(wrapper.emitted("close")).toBeUndefined();
  });
});
