<script setup lang="ts">
import Button from "primevue/button";
import Dialog from "primevue/dialog";
import { computed } from "vue";

import { clipDownloadUrl, clipStreamUrl, clipThumbnailUrl } from "@/api";
import { useFormatting } from "@/composables/useFormatting";
import VideoPlayer from "@/components/VideoPlayer.vue";

import type { ClipRead } from "@/api";

const props = withDefaults(
  defineProps<{
    clip: ClipRead | null;
    cameraName: string;
    canManage?: boolean;
  }>(),
  { canManage: true },
);

const emit = defineEmits<{
  close: [];
  delete: [];
}>();

const { formatDateTime, formatDuration, formatFileSize } = useFormatting();

const visible = computed({
  get: () => props.clip !== null,
  set: (value: boolean) => {
    if (!value) {
      emit("close");
    }
  },
});
</script>

<template>
  <Dialog
    v-model:visible="visible"
    modal
    :header="cameraName"
    :style="{ width: '52rem', maxWidth: '96vw' }"
    :breakpoints="{ '768px': '96vw' }"
    data-testid="clip-modal"
  >
    <template v-if="clip">
      <VideoPlayer
        v-if="clip.downloaded_at"
        :key="clip.id"
        :src="clipStreamUrl(clip.id)"
        :poster="clip.thumbnail_generated ? clipThumbnailUrl(clip.id) : undefined"
        class="player"
      />
      <p
        v-else
        class="muted"
      >
        This clip hasn't finished downloading yet.
      </p>

      <dl class="meta-grid">
        <div>
          <dt>Recorded</dt>
          <dd>{{ formatDateTime(clip.recorded_at) }}</dd>
        </div>
        <div>
          <dt>Duration</dt>
          <dd>{{ formatDuration(clip.duration_seconds) }}</dd>
        </div>
        <div>
          <dt>File size</dt>
          <dd>{{ formatFileSize(clip.file_size_bytes) }}</dd>
        </div>
      </dl>

      <div class="ai-section">
        <p class="ai-label">
          <i
            class="pi pi-sparkles"
            aria-hidden="true"
          /> AI summary
        </p>
        <p class="muted">
          AI analysis isn't enabled yet — a summary will appear here once it is.
        </p>
      </div>

      <div
        v-if="canManage"
        class="actions"
      >
        <a
          v-if="clip.downloaded_at"
          :href="clipDownloadUrl(clip.id)"
          class="p-button p-button-secondary p-button-outlined"
          data-testid="modal-download"
        >
          <i
            class="pi pi-download"
            aria-hidden="true"
            style="margin-right: 6px"
          />
          Download
        </a>
        <Button
          label="Delete"
          icon="pi pi-trash"
          severity="danger"
          text
          data-testid="modal-delete"
          @click="emit('delete')"
        />
      </div>
    </template>
  </Dialog>
</template>

<style scoped>
.player {
  margin-bottom: 18px;
}

.meta-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 14px;
  margin: 0 0 18px;
}

.meta-grid dt {
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--p-surface-500);
}

.meta-grid dd {
  margin: 4px 0 0;
  font-size: 0.92rem;
  font-weight: 600;
}

.ai-section {
  padding: 14px 16px;
  border-radius: 10px;
  border: 1px dashed var(--p-surface-300);
  margin-bottom: 18px;
}

.blink-dark .ai-section {
  border-color: var(--p-surface-700);
}

.ai-label {
  margin: 0 0 4px;
  font-size: 0.85rem;
  font-weight: 700;
}

.ai-label i {
  margin-right: 6px;
  color: var(--p-primary-500);
}

.muted {
  margin: 0;
  font-size: 0.85rem;
  color: var(--p-surface-500);
}

.actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
