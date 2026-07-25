import { mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("video.js", () => ({
  default: vi.fn(() => ({ dispose: vi.fn(), src: vi.fn() })),
}));
vi.mock("video.js/dist/video-js.css", () => ({}));

import videojs from "video.js";
import VideoPlayer from "@/components/VideoPlayer.vue";

const mockedVideojs = vi.mocked(videojs);

function lastPlayerInstance() {
  return mockedVideojs.mock.results.at(-1)?.value as { dispose: () => void; src: () => void };
}

beforeEach(() => {
  mockedVideojs.mockClear();
});

describe("VideoPlayer", () => {
  it("initializes video.js on mount with the given source", () => {
    const wrapper = mount(VideoPlayer, { props: { src: "/api/clips/1/stream" } });
    expect(mockedVideojs).toHaveBeenCalledOnce();
    const [, options] = mockedVideojs.mock.calls[0]!;
    expect(options).toMatchObject({
      controls: true,
      fluid: true,
      sources: [{ src: "/api/clips/1/stream", type: "video/mp4" }],
    });
    wrapper.unmount();
  });

  it("passes the poster through when provided", () => {
    const wrapper = mount(VideoPlayer, {
      props: { src: "/api/clips/1/stream", poster: "/thumb.jpg" },
    });
    const [, options] = mockedVideojs.mock.calls[0]!;
    expect(options).toMatchObject({ poster: "/thumb.jpg" });
    wrapper.unmount();
  });

  it("updates the player's source when the src prop changes", async () => {
    const wrapper = mount(VideoPlayer, { props: { src: "/api/clips/1/stream" } });
    const player = lastPlayerInstance();
    await wrapper.setProps({ src: "/api/clips/2/stream" });
    expect(player.src).toHaveBeenCalledWith({ src: "/api/clips/2/stream", type: "video/mp4" });
    wrapper.unmount();
  });

  it("disposes the player on unmount", () => {
    const wrapper = mount(VideoPlayer, { props: { src: "/api/clips/1/stream" } });
    const player = lastPlayerInstance();
    wrapper.unmount();
    expect(player.dispose).toHaveBeenCalledOnce();
  });
});
