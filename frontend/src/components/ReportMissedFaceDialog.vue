<script setup lang="ts">
import Button from "primevue/button";
import Dialog from "primevue/dialog";
import InputText from "primevue/inputtext";
import Message from "primevue/message";
import Select from "primevue/select";
import { computed, ref, watch } from "vue";

import { ApiError, createPerson, enrollFace, listPeople } from "@/api";
import ClipFramePicker from "@/components/ClipFramePicker.vue";

import type { DetectedFaceRead, PersonRead } from "@/api";

const props = defineProps<{
  clipId: string | null;
  durationSeconds: number | null;
}>();

const emit = defineEmits<{
  close: [];
  enrolled: [];
}>();

const visible = computed({
  get: () => props.clipId !== null,
  set: (value: boolean) => {
    if (!value) {
      emit("close");
    }
  },
});

const people = ref<PersonRead[]>([]);
const peopleError = ref("");
const currentSelection = ref<{ frameSeconds: number; face: DetectedFaceRead } | null>(null);
const selectedPersonId = ref<string | null>(null);
const newPersonName = ref("");
const submitting = ref(false);
const submitError = ref("");

function resetForNewSession(): void {
  currentSelection.value = null;
  selectedPersonId.value = null;
  newPersonName.value = "";
  submitError.value = "";
}

watch(
  () => props.clipId,
  (clipId) => {
    if (clipId === null) {
      return;
    }
    resetForNewSession();
    if (people.value.length === 0) {
      void loadPeople();
    }
  },
  { immediate: true },
);

async function loadPeople(): Promise<void> {
  peopleError.value = "";
  try {
    people.value = await listPeople();
  } catch (caught) {
    peopleError.value = caught instanceof ApiError ? caught.message : "Could not load people.";
  }
}

watch(selectedPersonId, (value) => {
  if (value !== null) {
    newPersonName.value = "";
  }
});

watch(newPersonName, (value) => {
  if (value.trim().length > 0) {
    selectedPersonId.value = null;
  }
});

const canSubmit = computed(
  () =>
    currentSelection.value !== null &&
    (selectedPersonId.value !== null || newPersonName.value.trim().length > 0),
);

async function confirm(): Promise<void> {
  // Only reachable via the button, which is disabled unless canSubmit.
  const clipId = props.clipId!;
  const selection = currentSelection.value!;
  submitting.value = true;
  submitError.value = "";
  try {
    const personId = selectedPersonId.value ?? (await createPerson({ name: newPersonName.value.trim() })).id;
    await enrollFace(personId, {
      clip_id: clipId,
      frame_seconds: selection.frameSeconds,
      bbox: selection.face.bbox,
    });
    emit("enrolled");
    visible.value = false;
  } catch (caught) {
    submitError.value = caught instanceof ApiError ? caught.message : "Could not enroll this face.";
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <Dialog
    v-model:visible="visible"
    modal
    header="Report a missed face"
    :style="{ width: '46rem', maxWidth: '96vw' }"
    :breakpoints="{ '768px': '96vw' }"
    data-testid="report-missed-face-dialog"
  >
    <div
      v-if="clipId"
      class="wizard"
    >
      <section class="step">
        <h4 class="step-title">
          1. Find the face
        </h4>
        <ClipFramePicker
          :key="clipId"
          :clip-id="clipId"
          :duration-seconds="durationSeconds"
          @selection-change="currentSelection = $event"
        />
      </section>

      <section class="step">
        <h4 class="step-title">
          2. Who is this?
        </h4>
        <Message
          v-if="peopleError"
          severity="error"
          :closable="false"
        >
          {{ peopleError }}
        </Message>
        <div class="who-grid">
          <label
            class="field"
            for="report-missed-person-select"
          >
            <span class="field-label">Enrolled person</span>
            <Select
              v-model="selectedPersonId"
              input-id="report-missed-person-select"
              :options="people"
              option-label="name"
              option-value="id"
              placeholder="Choose someone already enrolled"
              show-clear
              fluid
              data-testid="report-missed-person-select"
            />
          </label>
          <div class="or-divider">
            or
          </div>
          <label
            class="field"
            for="report-missed-new-person-name"
          >
            <span class="field-label">New person</span>
            <InputText
              id="report-missed-new-person-name"
              v-model="newPersonName"
              placeholder="e.g. Alex"
              fluid
              data-testid="report-missed-new-person-name"
            />
          </label>
        </div>
      </section>

      <Message
        v-if="submitError"
        severity="error"
        :closable="false"
        data-testid="report-missed-face-error"
      >
        {{ submitError }}
      </Message>
    </div>

    <template #footer>
      <Button
        label="Cancel"
        severity="secondary"
        text
        @click="visible = false"
      />
      <Button
        label="Enroll this face"
        :disabled="!canSubmit"
        :loading="submitting"
        data-testid="report-missed-face-confirm"
        @click="confirm"
      />
    </template>
  </Dialog>
</template>

<style scoped>
.wizard {
  display: flex;
  flex-direction: column;
  gap: 22px;
  max-height: 70vh;
  overflow-y: auto;
  padding-right: 4px;
}

.step {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.step-title {
  margin: 0;
  font-size: 0.85rem;
  font-weight: 700;
}

.who-grid {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 14px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex: 1 1 200px;
}

.field-label {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--p-surface-600);
}

.blink-dark .field-label {
  color: var(--p-surface-300);
}

.or-divider {
  font-size: 0.78rem;
  color: var(--p-surface-400);
  padding-bottom: 10px;
}
</style>
