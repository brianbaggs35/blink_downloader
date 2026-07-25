import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import ClipCard from "@/components/ClipCard.vue";
import { makePinia, mountGlobal } from "./helpers";

import type { ClipRead } from "@/api";

const baseClip: ClipRead = {
  id: "clip-1",
  camera_id: "cam-1",
  recorded_at: "2026-07-20T18:30:00Z",
  duration_seconds: 65,
  file_size_bytes: 1024,
  downloaded_at: "2026-07-20T18:31:00Z",
  deleted_on_blink: false,
  thumbnail_generated: true,
  recognized_people: [],
};

function mountCard(overrides: Partial<ClipRead> = {}, selected = false, selectable = true) {
  return mount(ClipCard, {
    props: { clip: { ...baseClip, ...overrides }, cameraName: "Front Door", selected, selectable },
    global: mountGlobal(makePinia()),
  });
}

describe("ClipCard", () => {
  it("shows the camera name and a formatted duration badge", () => {
    const wrapper = mountCard();
    expect(wrapper.find(".camera-name").text()).toBe("Front Door");
    expect(wrapper.find(".duration-badge").text()).toBe("1:05");
  });

  it("renders a thumbnail image when one has been generated", () => {
    const wrapper = mountCard();
    const img = wrapper.find("img");
    expect(img.exists()).toBe(true);
    expect(img.attributes("src")).toBe("/api/clips/clip-1/thumbnail");
  });

  it("falls back to a placeholder icon when there is no thumbnail", () => {
    const wrapper = mountCard({ thumbnail_generated: false });
    expect(wrapper.find("img").exists()).toBe(false);
    expect(wrapper.find(".thumb-fallback i.pi-video").exists()).toBe(true);
  });

  it("falls back to the placeholder if the thumbnail image fails to load", async () => {
    const wrapper = mountCard();
    await wrapper.find("img").trigger("error");
    expect(wrapper.find("img").exists()).toBe(false);
    expect(wrapper.find(".thumb-fallback").exists()).toBe(true);
  });

  it("shows a pending badge while the clip hasn't finished downloading", () => {
    const wrapper = mountCard({ downloaded_at: null });
    expect(wrapper.find(".pending-badge").text()).toBe("Downloading…");
  });

  it("omits the duration badge when duration is unknown", () => {
    const wrapper = mountCard({ duration_seconds: null });
    expect(wrapper.find(".duration-badge").exists()).toBe(false);
  });

  it("emits open when the card is clicked", async () => {
    const wrapper = mountCard();
    await wrapper.find('[data-testid="clip-card"]').trigger("click");
    expect(wrapper.emitted("open")).toHaveLength(1);
  });

  it("applies the selected class and reflects the selected prop on the checkbox", () => {
    const wrapper = mountCard({}, true);
    expect(wrapper.find(".card").classes()).toContain("selected");
  });

  it("clicking the checkbox does not also open the clip", async () => {
    const wrapper = mountCard();
    await wrapper.find(".checkbox-overlay").trigger("click");
    expect(wrapper.emitted("open")).toBeUndefined();
  });

  it("emits update:selected when the checkbox changes", async () => {
    const wrapper = mountCard();
    await wrapper.findComponent({ name: "Checkbox" }).vm.$emit("update:modelValue", true);
    expect(wrapper.emitted("update:selected")?.[0]).toEqual([true]);
  });

  it("hides the selection checkbox when not selectable (viewer accounts)", () => {
    const wrapper = mountCard({}, false, false);
    expect(wrapper.find(".checkbox-overlay").exists()).toBe(false);
    expect(wrapper.findComponent({ name: "Checkbox" }).exists()).toBe(false);
  });

  it("omits the recognized badge when nobody was recognized", () => {
    const wrapper = mountCard();
    expect(wrapper.find('[data-testid="recognized-badge"]').exists()).toBe(false);
  });

  it("shows a recognized badge with a count and name tooltip", () => {
    const wrapper = mountCard({
      recognized_people: [
        { id: "p-1", name: "Alex" },
        { id: "p-2", name: "Sam" },
      ],
    });
    const badge = wrapper.find('[data-testid="recognized-badge"]');
    expect(badge.text()).toContain("2");
    expect(badge.attributes("title")).toBe("Recognized: Alex, Sam");
  });
});
