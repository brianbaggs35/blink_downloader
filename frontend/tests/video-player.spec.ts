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

  it("uses the given source type instead of the video/mp4 default", () => {
    const wrapper = mount(VideoPlayer, {
      props: { src: "/api/x/stream.m3u8", type: "application/x-mpegURL" },
    });
    const [, options] = mockedVideojs.mock.calls[0]!;
    expect(options).toMatchObject({
      sources: [{ src: "/api/x/stream.m3u8", type: "application/x-mpegURL" }],
    });
    wrapper.unmount();
  });

  it("configures fill/liveui and drops playback rates for a live stream", () => {
    const wrapper = mount(VideoPlayer, {
      props: { src: "tcp-relay-playlist.m3u8", live: true },
    });
    const [, options] = mockedVideojs.mock.calls[0]!;
    expect(options).toMatchObject({ fluid: false, fill: true, liveui: true, playbackRates: [] });
    expect(wrapper.find("[data-vjs-player]").classes()).toContain("live-fill");
    wrapper.unmount();
  });

  it("defaults to fluid mode with playback rates for a non-live source", () => {
    const wrapper = mount(VideoPlayer, { props: { src: "/api/clips/1/stream" } });
    const [, options] = mockedVideojs.mock.calls[0]!;
    expect(options).toMatchObject({ fluid: true, fill: false, liveui: false });
    expect((options as { playbackRates: number[] }).playbackRates.length).toBeGreaterThan(0);
    expect(wrapper.find("[data-vjs-player]").classes()).not.toContain("live-fill");
    wrapper.unmount();
  });

  it("updates the player's source with a custom type when src changes", async () => {
    const wrapper = mount(VideoPlayer, {
      props: { src: "/a.m3u8", type: "application/x-mpegURL" },
    });
    const player = lastPlayerInstance();
    await wrapper.setProps({ src: "/b.m3u8", type: "application/x-mpegURL" });
    expect(player.src).toHaveBeenCalledWith({ src: "/b.m3u8", type: "application/x-mpegURL" });
    wrapper.unmount();
  });

  it("disposes the player on unmount", () => {
    const wrapper = mount(VideoPlayer, { props: { src: "/api/clips/1/stream" } });
    const player = lastPlayerInstance();
    wrapper.unmount();
    expect(player.dispose).toHaveBeenCalledOnce();
  });
});
