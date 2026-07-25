<script setup lang="ts">
import "video.js/dist/video-js.css";
import videojs from "video.js";
import { onBeforeUnmount, onMounted, ref, watch } from "vue";

import type Player from "video.js/dist/types/player";

const props = defineProps<{ src: string; poster?: string }>();

const videoRef = ref<HTMLVideoElement | null>(null);
let player: Player | null = null;

onMounted(() => {
  player = videojs(videoRef.value!, {
    controls: true,
    fluid: true,
    preload: "metadata",
    playbackRates: [0.5, 1, 1.5, 2],
    poster: props.poster,
    sources: [{ src: props.src, type: "video/mp4" }],
  });
});

watch(
  () => props.src,
  (src) => {
    player?.src({ src, type: "video/mp4" });
  },
);

onBeforeUnmount(() => {
  // video.js takes over the DOM node it's given; disposing is required or
  // repeated mount/unmount (opening the clip modal more than once) leaks
  // players and can throw on the next mount.
  player?.dispose();
  player = null;
});

defineExpose({ videoRef });
</script>

<template>
  <div data-vjs-player>
    <video
      ref="videoRef"
      class="video-js vjs-big-play-centered"
      playsinline
    />
  </div>
</template>

<style scoped>
:deep(.video-js) {
  border-radius: 10px;
  overflow: hidden;
}

:deep(.vjs-big-play-button) {
  border-color: var(--p-primary-400);
  background-color: color-mix(in srgb, var(--p-surface-900) 60%, transparent);
}

:deep(.vjs-control-bar) {
  background-color: color-mix(in srgb, var(--p-surface-950) 70%, transparent);
}
</style>
