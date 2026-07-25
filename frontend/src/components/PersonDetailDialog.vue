<script setup lang="ts">
import Button from "primevue/button";
import Dialog from "primevue/dialog";
import InputText from "primevue/inputtext";
import Message from "primevue/message";
import Skeleton from "primevue/skeleton";
import { useConfirm } from "primevue/useconfirm";
import { useToast } from "primevue/usetoast";
import { computed, ref, watch } from "vue";

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
import { useFormatting } from "@/composables/useFormatting";
import { useAuthStore } from "@/stores/auth";

import type { FaceEmbeddingRead, PersonRead } from "@/api";

const props = defineProps<{
  personId: string | null;
}>();

const emit = defineEmits<{
  close: [];
  "enroll-more": [];
  deleted: [];
}>();

const auth = useAuthStore();
const toast = useToast();
const confirm = useConfirm();
const { formatDateTime } = useFormatting();

const visible = computed({
  get: () => props.personId !== null,
  set: (value: boolean) => {
    if (!value) {
      emit("close");
    }
  },
});

const person = ref<PersonRead | null>(null);
const faces = ref<FaceEmbeddingRead[]>([]);
const loading = ref(true);
const loadError = ref("");

async function load(personId: string): Promise<void> {
  loading.value = true;
  loadError.value = "";
  try {
    const [loadedPerson, loadedFaces] = await Promise.all([
      getPerson(personId),
      listPersonFaces(personId),
    ]);
    person.value = loadedPerson;
    faces.value = loadedFaces;
  } catch (caught) {
    loadError.value = caught instanceof ApiError ? caught.message : "Could not load this person.";
  } finally {
    loading.value = false;
  }
}

watch(
  () => props.personId,
  (personId) => {
    if (personId) {
      void load(personId);
    }
  },
  { immediate: true },
);

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
  const personId = props.personId!;
  if (!nameDraft.value.trim()) {
    return;
  }
  savingName.value = true;
  renameError.value = "";
  try {
    person.value = await updatePerson(personId, { name: nameDraft.value.trim() });
    editingName.value = false;
  } catch (caught) {
    renameError.value = caught instanceof ApiError ? caught.message : "Could not rename.";
  } finally {
    savingName.value = false;
  }
}

const deletingFaceId = ref<string | null>(null);

function confirmDeleteFace(face: FaceEmbeddingRead): void {
  confirm.require({
    message: "Delete this face sample? This can't be undone.",
    header: "Delete face sample",
    icon: "pi pi-exclamation-triangle",
    acceptProps: { label: "Delete", severity: "danger" },
    rejectProps: { label: "Cancel", severity: "secondary", outlined: true },
    accept: () => void performDeleteFace(face),
  });
}

async function performDeleteFace(face: FaceEmbeddingRead): Promise<void> {
  const personId = props.personId!;
  deletingFaceId.value = face.id;
  try {
    await deleteFace(personId, face.id);
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
  // Only reachable via the footer button, rendered inside the
  // v-else-if="person" block.
  confirm.require({
    message: `Delete ${person.value!.name}? This removes all of their enrolled faces too.`,
    header: "Delete person",
    icon: "pi pi-exclamation-triangle",
    acceptProps: { label: "Delete", severity: "danger" },
    rejectProps: { label: "Cancel", severity: "secondary", outlined: true },
    accept: () => void performDeletePerson(),
  });
}

async function performDeletePerson(): Promise<void> {
  const personId = props.personId!;
  deletingPerson.value = true;
  try {
    await deletePerson(personId);
    emit("deleted");
    visible.value = false;
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
</script>

<template>
  <Dialog
    v-model:visible="visible"
    modal
    header="Enrolled person"
    :style="{ width: '40rem', maxWidth: '96vw' }"
    data-testid="person-detail-dialog"
  >
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
        </template>
      </div>
      <Message
        v-if="renameError"
        severity="error"
        :closable="false"
      >
        {{ renameError }}
      </Message>

      <p class="muted">
        {{ faces.length }} enrolled face sample(s)
      </p>

      <EmptyState
        v-if="faces.length === 0"
        icon="pi pi-images"
        title="No face samples yet"
        description="Enroll a face from a clip to help recognition find this person."
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
    </div>

    <template
      v-if="auth.isAdmin"
      #footer
    >
      <Button
        label="Delete person"
        severity="danger"
        text
        :loading="deletingPerson"
        data-testid="delete-person"
        @click="confirmDeletePerson"
      />
      <Button
        label="Enroll another face"
        icon="pi pi-plus"
        data-testid="enroll-more"
        @click="emit('enroll-more')"
      />
    </template>
  </Dialog>
</template>

<style scoped>
.detail {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.name-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.person-name {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 700;
}

.muted {
  margin: 0;
  font-size: 0.82rem;
  color: var(--p-surface-500);
}

.face-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
  gap: 12px;
  max-height: 320px;
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
