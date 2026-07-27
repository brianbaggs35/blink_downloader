<script setup lang="ts">
import Button from "primevue/button";
import Dialog from "primevue/dialog";
import Message from "primevue/message";
import Skeleton from "primevue/skeleton";
import Tag from "primevue/tag";
import { useToast } from "primevue/usetoast";
import { computed, ref, watch } from "vue";

import {
  ApiError,
  clipDownloadUrl,
  clipStreamUrl,
  clipThumbnailUrl,
  getClipAnalysis,
  reanalyzeClip,
  reportFalsePositive,
  submitFeedback,
} from "@/api";
import ReportMissedFaceDialog from "@/components/ReportMissedFaceDialog.vue";
import VideoPlayer from "@/components/VideoPlayer.vue";
import { useDeleteConfirm } from "@/composables/useDeleteConfirm";
import { useFormatting } from "@/composables/useFormatting";

import type { AnalysisRead, ClipRead, FeedbackVerdict } from "@/api";

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
const toast = useToast();
const { confirmDelete } = useDeleteConfirm();

const visible = computed({
  get: () => props.clip !== null,
  set: (value: boolean) => {
    if (!value) {
      emit("close");
    }
  },
});

const LABEL_SEVERITY: Record<AnalysisRead["suspicion_label"], "success" | "warn" | "danger"> = {
  routine: "success",
  uncertain: "warn",
  suspicious: "danger",
};

const analysis = ref<AnalysisRead | null>(null);
const analysisLoading = ref(true);
const analysisError = ref("");
const notAnalyzed = ref(false);
const feedbackGiven = ref(false);
const submittingFeedback = ref(false);
const reanalyzing = ref(false);

async function loadAnalysis(clipId: string): Promise<void> {
  analysisLoading.value = true;
  analysisError.value = "";
  notAnalyzed.value = false;
  analysis.value = null;
  try {
    analysis.value = await getClipAnalysis(clipId);
  } catch (caught) {
    if (caught instanceof ApiError && caught.status === 404) {
      notAnalyzed.value = true;
    } else {
      analysisError.value =
        caught instanceof ApiError ? caught.message : "Could not load AI analysis.";
    }
  } finally {
    analysisLoading.value = false;
  }
}

watch(
  () => props.clip?.id,
  (clipId) => {
    feedbackGiven.value = false;
    if (clipId) {
      void loadAnalysis(clipId);
    }
  },
  { immediate: true },
);

interface VehicleProximityInfo {
  distanceFeet: number;
  errorMarginFeet: number;
  breached: boolean;
}

const proximity = computed<VehicleProximityInfo | null>(() => {
  const raw = analysis.value?.vehicle_proximity;
  if (!raw) {
    return null;
  }
  return {
    distanceFeet: raw.distance_feet as number,
    errorMarginFeet: raw.error_margin_feet as number,
    breached: raw.breached_threshold as boolean,
  };
});

async function triggerReanalyze(): Promise<void> {
  // Only reachable via the button inside the template's v-if="clip" block.
  const clip = props.clip!;
  reanalyzing.value = true;
  try {
    await reanalyzeClip(clip.id);
    toast.add({ severity: "success", summary: "Analysis queued", life: 2500 });
  } catch (caught) {
    toast.add({
      severity: "error",
      summary: "Could not queue analysis",
      detail: caught instanceof ApiError ? caught.message : "Unexpected error.",
      life: 4000,
    });
  } finally {
    reanalyzing.value = false;
  }
}

async function giveFeedback(verdict: FeedbackVerdict): Promise<void> {
  // Only reachable via the buttons inside the template's v-if="clip" block.
  const clip = props.clip!;
  submittingFeedback.value = true;
  try {
    await submitFeedback(clip.id, { verdict, note: null });
    feedbackGiven.value = true;
  } catch (caught) {
    toast.add({
      severity: "error",
      summary: "Could not record feedback",
      detail: caught instanceof ApiError ? caught.message : "Unexpected error.",
      life: 4000,
    });
  } finally {
    submittingFeedback.value = false;
  }
}

const reportingPersonId = ref<string | null>(null);

function confirmReportFalsePositive(personId: string, name: string): void {
  confirmDelete({
    header: "Report incorrect recognition",
    message: `Report that ${name} was recognized here by mistake? This also teaches the system to stop matching this specific face to them.`,
    acceptLabel: "Report",
    onAccept: () => void performReportFalsePositive(personId),
  });
}

async function performReportFalsePositive(personId: string): Promise<void> {
  // Only reachable via a recognized-entity tag inside the template's
  // v-if="clip" block.
  const clip = props.clip!;
  reportingPersonId.value = personId;
  try {
    await reportFalsePositive(clip.id, personId);
    toast.add({ severity: "success", summary: "Thanks — recognition corrected", life: 3000 });
    await loadAnalysis(clip.id);
  } catch (caught) {
    toast.add({
      severity: "error",
      summary: "Could not report this recognition",
      detail: caught instanceof ApiError ? caught.message : "Unexpected error.",
      life: 4000,
    });
  } finally {
    reportingPersonId.value = null;
  }
}

const missedFaceClipId = ref<string | null>(null);

function openMissedFaceDialog(): void {
  // Only reachable via the button inside the template's v-if="clip" block.
  missedFaceClipId.value = props.clip!.id;
}

async function onMissedFaceEnrolled(): Promise<void> {
  toast.add({
    severity: "success",
    summary: "Face enrolled",
    detail: "Re-analyze this clip to apply it here.",
    life: 4000,
  });
  if (props.clip) {
    await loadAnalysis(props.clip.id);
  }
}
</script>

<template>
  <Dialog
    v-model:visible="visible"
    modal
    maximizable
    :header="cameraName"
    :style="{ width: '78rem', maxWidth: '96vw' }"
    :breakpoints="{ '1100px': '92vw', '768px': '100vw' }"
    class="clip-modal"
    data-testid="clip-modal"
  >
    <template v-if="clip">
      <div class="modal-layout">
        <div class="modal-main">
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
        </div>

        <div class="modal-sidebar">
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
            <div class="ai-header">
              <p class="ai-label">
                <i
                  class="pi pi-sparkles"
                  aria-hidden="true"
                /> AI summary
              </p>
              <div
                v-if="clip.downloaded_at"
                class="ai-header-actions"
              >
                <Button
                  label="Report a missed face"
                  icon="pi pi-user-plus"
                  text
                  size="small"
                  severity="secondary"
                  data-testid="report-missed-face"
                  @click="openMissedFaceDialog"
                />
                <Button
                  v-if="canManage"
                  :label="analysis ? 'Re-analyze' : 'Analyze now'"
                  text
                  size="small"
                  :loading="reanalyzing"
                  data-testid="reanalyze"
                  @click="triggerReanalyze"
                />
              </div>
            </div>

            <div
              v-if="analysisLoading"
              data-testid="analysis-loading"
            >
              <Skeleton height="52px" />
            </div>

            <Message
              v-else-if="analysisError"
              severity="error"
              :closable="false"
              data-testid="analysis-error"
            >
              {{ analysisError }}
            </Message>

            <p
              v-else-if="notAnalyzed"
              class="muted"
              data-testid="analysis-not-yet"
            >
              This clip hasn't been analyzed yet.
            </p>

            <div
              v-else-if="analysis"
              class="analysis-body"
              data-testid="analysis-body"
            >
              <div class="analysis-top">
                <Tag
                  :value="analysis.suspicion_label"
                  :severity="LABEL_SEVERITY[analysis.suspicion_label]"
                  class="label-tag"
                />
                <span class="score">{{ Math.round(analysis.suspicion_score * 100) }}% suspicion</span>
                <Tag
                  v-if="analysis.escalated"
                  value="Escalated to Tier 2"
                  severity="info"
                />
              </div>

              <p class="summary-text">
                {{ analysis.summary }}
              </p>

              <div
                v-if="analysis.detected_entities.length > 0"
                class="entities"
              >
                <span
                  v-for="(entity, index) in analysis.detected_entities"
                  :key="index"
                  class="entity-tag"
                  :class="{ recognized: entity.recognized_person_id }"
                  :data-testid="entity.recognized_person_id ? 'recognized-entity-tag' : undefined"
                >
                  <i
                    v-if="entity.recognized_person_id"
                    class="pi pi-verified"
                    aria-hidden="true"
                  />
                  {{ entity.label }} ({{ Math.round(entity.confidence * 100) }}%)
                  <button
                    v-if="entity.recognized_person_id && canManage"
                    type="button"
                    class="report-mismatch"
                    :disabled="reportingPersonId === entity.recognized_person_id"
                    :data-testid="`report-false-positive-${entity.recognized_person_id}`"
                    :aria-label="`Report that ${entity.label} was recognized by mistake`"
                    @click="
                      entity.recognized_person_id &&
                        confirmReportFalsePositive(entity.recognized_person_id, entity.label)
                    "
                  >
                    <i
                      class="pi pi-times-circle"
                      aria-hidden="true"
                    />
                  </button>
                </span>
              </div>

              <p
                v-if="proximity"
                class="proximity"
                :class="{ breach: proximity.breached }"
                data-testid="proximity-note"
              >
                <i
                  class="pi pi-car"
                  aria-hidden="true"
                />
                ~{{ proximity.distanceFeet.toFixed(1) }} ft (±{{ proximity.errorMarginFeet.toFixed(1) }} ft)
                from the vehicle
              </p>

              <div class="feedback-row">
                <span
                  v-if="feedbackGiven"
                  class="feedback-thanks"
                  data-testid="feedback-thanks"
                >
                  <i
                    class="pi pi-check"
                    aria-hidden="true"
                  /> Thanks for the feedback
                </span>
                <template v-else>
                  <span class="feedback-prompt">Was this right?</span>
                  <Button
                    label="Correct"
                    size="small"
                    text
                    :loading="submittingFeedback"
                    data-testid="feedback-correct"
                    @click="giveFeedback('correct')"
                  />
                  <Button
                    v-if="analysis.suspicion_label === 'routine'"
                    label="Actually suspicious"
                    size="small"
                    text
                    severity="secondary"
                    :loading="submittingFeedback"
                    data-testid="feedback-false-negative"
                    @click="giveFeedback('false_negative')"
                  />
                  <Button
                    v-else
                    label="Not suspicious"
                    size="small"
                    text
                    severity="secondary"
                    :loading="submittingFeedback"
                    data-testid="feedback-false-positive"
                    @click="giveFeedback('false_positive')"
                  />
                </template>
              </div>
            </div>
          </div>
        </div>
      </div>
    </template>
  </Dialog>

  <ReportMissedFaceDialog
    :clip-id="missedFaceClipId"
    :duration-seconds="clip?.duration_seconds ?? null"
    @close="missedFaceClipId = null"
    @enrolled="onMissedFaceEnrolled"
  />
</template>

<style scoped>
.modal-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: 24px;
  align-items: start;
}

.modal-main {
  min-width: 0;
}

.modal-sidebar {
  max-height: 75vh;
  overflow-y: auto;
  padding-right: 4px;
}

@media (max-width: 900px) {
  .modal-layout {
    grid-template-columns: minmax(0, 1fr);
  }

  .modal-sidebar {
    max-height: none;
    overflow-y: visible;
  }
}

.player {
  margin-bottom: 14px;
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

.ai-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.ai-header-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}

.ai-label {
  margin: 0;
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

.analysis-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.analysis-top {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.label-tag {
  text-transform: capitalize;
}

.score {
  font-size: 0.82rem;
  color: var(--p-surface-600);
}

.blink-dark .score {
  color: var(--p-surface-300);
}

.summary-text {
  margin: 0;
  font-size: 0.88rem;
  line-height: 1.5;
}

.entities {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.entity-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 10px;
  border-radius: 999px;
  background: var(--p-surface-100);
  font-size: 0.76rem;
  color: var(--p-surface-600);
}

.blink-dark .entity-tag {
  background: var(--p-surface-800);
  color: var(--p-surface-300);
}

.entity-tag.recognized {
  background: color-mix(in srgb, var(--p-primary-500) 18%, transparent);
  color: var(--p-primary-700);
  font-weight: 600;
}

.blink-dark .entity-tag.recognized {
  color: var(--p-primary-300);
}

.report-mismatch {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: none;
  padding: 0;
  margin-left: 2px;
  cursor: pointer;
  color: inherit;
  opacity: 0.6;
  font-size: 0.9em;
}

.report-mismatch:hover {
  opacity: 1;
  color: var(--p-red-600);
}

.blink-dark .report-mismatch:hover {
  color: var(--p-red-300);
}

.report-mismatch:disabled {
  cursor: default;
  opacity: 0.35;
}

.proximity {
  margin: 0;
  padding: 8px 12px;
  border-radius: 8px;
  background: var(--p-surface-100);
  font-size: 0.82rem;
}

.blink-dark .proximity {
  background: var(--p-surface-800);
}

.proximity.breach {
  background: color-mix(in srgb, var(--p-red-500) 15%, transparent);
  color: var(--p-red-600);
  font-weight: 600;
}

.blink-dark .proximity.breach {
  color: var(--p-red-300);
}

.feedback-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding-top: 4px;
}

.feedback-prompt {
  font-size: 0.8rem;
  color: var(--p-surface-500);
}

.feedback-thanks {
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--p-green-600);
}

.blink-dark .feedback-thanks {
  color: var(--p-green-300);
}

.actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
