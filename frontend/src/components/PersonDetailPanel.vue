<script setup lang="ts">
import Button from "primevue/button";
import InputText from "primevue/inputtext";
import Message from "primevue/message";
import Skeleton from "primevue/skeleton";
import ToggleSwitch from "primevue/toggleswitch";
import { useToast } from "primevue/usetoast";
import { ref, watch } from "vue";

import {
  ApiError,
  deleteFace,
  deletePerson,
  faceThumbnailUrl,
  getPerson,
  listPersonFaces,
  updatePerson,
} from "@/api";
import EmptyState from "@/components/EmptyState.vue";
import PersonEnrollmentPanel from "@/components/PersonEnrollmentPanel.vue";
import { useDeleteConfirm } from "@/composables/useDeleteConfirm";
import { useFormatting } from "@/composables/useFormatting";
import { useAuthStore } from "@/stores/auth";

import type { FaceEmbeddingRead, PersonRead } from "@/api";

const props = defineProps<{
  personId: string;
}>();

const emit = defineEmits<{
  deleted: [];
}>();

const auth = useAuthStore();
const toast = useToast();
const { confirmDelete } = useDeleteConfirm();
const { formatDateTime } = useFormatting();

const person = ref<PersonRead | null>(null);
const faces = ref<FaceEmbeddingRead[]>([]);
const loading = ref(true);
const loadError = ref("");

async function load(): Promise<void> {
  loading.value = true;
  loadError.value = "";
  try {
    const [loadedPerson, loadedFaces] = await Promise.all([
      getPerson(props.personId),
      listPersonFaces(props.personId),
    ]);
    person.value = loadedPerson;
    faces.value = loadedFaces;
  } catch (caught) {
    loadError.value = caught instanceof ApiError ? caught.message : "Could not load this person.";
  } finally {
    loading.value = false;
  }
}

watch(() => props.personId, load, { immediate: true });

const editingName = ref(false);
const nameDraft = ref("");
const savingName = ref(false);
const renameError = ref("");

function startEditingName(): void {
  // Only reachable via the pencil button, rendered inside the
  // v-else-if="person" block.
  nameDraft.value = person.value!.name;
  renameError.value = "";
  editingName.value = true;
}

async function saveName(): Promise<void> {
  // Only reachable via the save button inside the v-if="person" block.
  if (!nameDraft.value.trim()) {
    return;
  }
  savingName.value = true;
  renameError.value = "";
  try {
    person.value = await updatePerson(props.personId, {
      name: nameDraft.value.trim(),
      never_mark_suspicious: person.value!.never_mark_suspicious,
    });
    editingName.value = false;
  } catch (caught) {
    renameError.value = caught instanceof ApiError ? caught.message : "Could not rename.";
  } finally {
    savingName.value = false;
  }
}

const savingNeverMarkSuspicious = ref(false);

async function toggleNeverMarkSuspicious(value: boolean): Promise<void> {
  // Only reachable via the toggle inside the v-else-if="person" block.
  savingNeverMarkSuspicious.value = true;
  try {
    person.value = await updatePerson(props.personId, {
      name: person.value!.name,
      never_mark_suspicious: value,
    });
  } catch (caught) {
    toast.add({
      severity: "error",
      summary: "Could not update this person",
      detail: caught instanceof ApiError ? caught.message : "Unexpected error.",
      life: 4000,
    });
  } finally {
    savingNeverMarkSuspicious.value = false;
  }
}

const deletingFaceId = ref<string | null>(null);

function confirmDeleteFace(face: FaceEmbeddingRead): void {
  confirmDelete({
    header: "Delete face sample",
    message: "Delete this face sample? This can't be undone.",
    onAccept: () => void performDeleteFace(face),
  });
}

async function performDeleteFace(face: FaceEmbeddingRead): Promise<void> {
  deletingFaceId.value = face.id;
  try {
    await deleteFace(props.personId, face.id);
    faces.value = faces.value.filter((f) => f.id !== face.id);
    // person is always loaded alongside faces (see load()) by the time this
    // button is reachable.
    person.value = { ...person.value!, face_count: person.value!.face_count - 1 };
  } catch (caught) {
    toast.add({
      severity: "error",
      summary: "Could not delete face sample",
      detail: caught instanceof ApiError ? caught.message : "Unexpected error.",
      life: 4000,
    });
  } finally {
    deletingFaceId.value = null;
  }
}

const deletingPerson = ref(false);

function confirmDeletePerson(): void {
  // Only reachable via the button, rendered inside the v-else-if="person" block.
  confirmDelete({
    header: "Delete person",
    message: `Delete ${person.value!.name}? This removes all of their enrolled faces too.`,
    onAccept: () => void performDeletePerson(),
  });
}

async function performDeletePerson(): Promise<void> {
  deletingPerson.value = true;
  try {
    await deletePerson(props.personId);
    emit("deleted");
  } catch (caught) {
    toast.add({
      severity: "error",
      summary: "Could not delete person",
      detail: caught instanceof ApiError ? caught.message : "Unexpected error.",
      life: 4000,
    });
  } finally {
    deletingPerson.value = false;
  }
}

async function onEnrolled(): Promise<void> {
  // Only reachable via the embedded PersonEnrollmentPanel, itself only
  // rendered inside the template's v-else-if="person" block.
  faces.value = await listPersonFaces(props.personId);
  person.value = { ...person.value!, face_count: faces.value.length };
}
</script>

<template>
  <div
    v-if="loading"
    data-testid="person-detail-loading"
  >
    <Skeleton
      height="220px"
      border-radius="12px"
    />
  </div>

  <Message
    v-else-if="loadError"
    severity="error"
    :closable="false"
  >
    {{ loadError }}
  </Message>

  <div
    v-else-if="person"
    class="detail"
    data-testid="person-detail-panel"
  >
    <div class="name-row">
      <template v-if="editingName">
        <InputText
          v-model="nameDraft"
          fluid
          data-testid="person-name-input"
          @keyup.enter="saveName"
        />
        <Button
          icon="pi pi-check"
          :loading="savingName"
          data-testid="person-name-save"
          @click="saveName"
        />
        <Button
          icon="pi pi-times"
          severity="secondary"
          text
          data-testid="person-name-cancel"
          @click="editingName = false"
        />
      </template>
      <template v-else>
        <h3 class="person-name">
          {{ person.name }}
        </h3>
        <Button
          v-if="auth.isAdmin"
          icon="pi pi-pencil"
          severity="secondary"
          text
          size="small"
          data-testid="person-rename-start"
          @click="startEditingName"
        />
        <Button
          v-if="auth.isAdmin"
          label="Delete person"
          icon="pi pi-trash"
          severity="danger"
          text
          size="small"
          class="delete-person-button"
          :loading="deletingPerson"
          data-testid="delete-person"
          @click="confirmDeletePerson"
        />
      </template>
    </div>
    <Message
      v-if="renameError"
      severity="error"
      :closable="false"
    >
      {{ renameError }}
    </Message>

    <div
      v-if="auth.isAdmin"
      class="toggle-row"
    >
      <ToggleSwitch
        :model-value="person.never_mark_suspicious"
        :disabled="savingNeverMarkSuspicious"
        data-testid="never-mark-suspicious-toggle"
        @update:model-value="toggleNeverMarkSuspicious"
      />
      <div>
        <p class="toggle-label">
          Never mark suspicious
        </p>
        <p class="muted">
          Clips where {{ person.name }} is recognized are always labeled routine, even if the AI
          flags them.
        </p>
      </div>
    </div>

    <section class="section">
      <h4 class="section-title">
        {{ faces.length }} enrolled face sample(s)
      </h4>

      <EmptyState
        v-if="faces.length === 0"
        icon="pi pi-images"
        title="No face samples yet"
        description="Enroll a face from a clip below to help recognition find this person."
      />

      <div
        v-else
        class="face-grid"
        data-testid="face-grid"
      >
        <div
          v-for="face in faces"
          :key="face.id"
          class="face-item"
          :data-testid="`face-item-${face.id}`"
        >
          <img
            :src="faceThumbnailUrl(person.id, face.id)"
            alt="Enrolled face sample"
            class="face-thumb"
          >
          <span class="face-date">{{ formatDateTime(face.created_at) }}</span>
          <Button
            v-if="auth.isAdmin"
            icon="pi pi-trash"
            severity="danger"
            text
            size="small"
            :loading="deletingFaceId === face.id"
            :data-testid="`delete-face-${face.id}`"
            @click="confirmDeleteFace(face)"
          />
        </div>
      </div>
    </section>

    <section class="section">
      <h4 class="section-title">
        Add a face from a clip
      </h4>
      <p class="muted">
        The more samples you add — different angles, lighting, and times of day — the more
        accurate recognition gets for {{ person.name }}.
      </p>
      <PersonEnrollmentPanel
        :key="person.id"
        :person-id="person.id"
        @enrolled="onEnrolled"
      />
    </section>
  </div>
</template>

<style scoped>
.detail {
  display: flex;
  flex-direction: column;
  gap: 28px;
}

.name-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.person-name {
  margin: 0;
  font-size: 1.3rem;
  font-weight: 700;
}

.delete-person-button {
  margin-left: auto;
}

.toggle-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.toggle-label {
  margin: 0;
  font-size: 0.9rem;
  font-weight: 600;
}

.muted {
  margin: 2px 0 0;
  font-size: 0.8rem;
  color: var(--p-surface-500);
}

.section {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-top: 20px;
  border-top: 1px solid var(--p-surface-200);
}

.blink-dark .section {
  border-color: var(--p-surface-800);
}

.section-title {
  margin: 0;
  font-size: 0.85rem;
  font-weight: 700;
  color: var(--p-surface-600);
}

.blink-dark .section-title {
  color: var(--p-surface-300);
}

.face-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
  gap: 12px;
  max-height: 400px;
  overflow-y: auto;
  padding: 4px 4px 4px 0;
}

.face-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 8px;
  border-radius: 10px;
  background: var(--p-surface-50);
}

.blink-dark .face-item {
  background: color-mix(in srgb, var(--p-surface-800) 55%, transparent);
}

.face-thumb {
  width: 88px;
  height: 88px;
  border-radius: 8px;
  object-fit: cover;
}

.face-date {
  font-size: 0.68rem;
  color: var(--p-surface-500);
}
</style>
