<script setup lang="ts">
import Button from "primevue/button";
import Dialog from "primevue/dialog";
import InputText from "primevue/inputtext";
import Message from "primevue/message";
import Skeleton from "primevue/skeleton";
import { useToast } from "primevue/usetoast";
import { onMounted, ref } from "vue";

import { ApiError, createPerson, listPeople, personThumbnailUrl } from "@/api";
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
import PersonDetailPanel from "@/components/PersonDetailPanel.vue";

import type { PersonRead } from "@/api";

const toast = useToast();

const people = ref<PersonRead[]>([]);
const loading = ref(true);
const loadError = ref("");

async function load(): Promise<void> {
  loading.value = true;
  loadError.value = "";
  try {
    people.value = await listPeople();
  } catch (caught) {
    loadError.value = caught instanceof ApiError ? caught.message : "Could not load people.";
  } finally {
    loading.value = false;
  }
}

onMounted(load);

const selectedPersonId = ref<string | null>(null);

function backToList(): void {
  selectedPersonId.value = null;
  void load();
}

const addDialogVisible = ref(false);
const newPersonName = ref("");
const creating = ref(false);
const createError = ref("");

function openAddDialog(): void {
  newPersonName.value = "";
  createError.value = "";
  addDialogVisible.value = true;
}

async function submitNewPerson(): Promise<void> {
  if (!newPersonName.value.trim()) {
    return;
  }
  creating.value = true;
  createError.value = "";
  try {
    const person = await createPerson({ name: newPersonName.value.trim() });
    addDialogVisible.value = false;
    // Straight into the detail view so they can enroll the person's first
    // face right away, rather than back to a grid they'd have to re-click.
    selectedPersonId.value = person.id;
  } catch (caught) {
    createError.value = caught instanceof ApiError ? caught.message : "Could not create person.";
  } finally {
    creating.value = false;
  }
}

function onPersonDeleted(): void {
  toast.add({ severity: "success", summary: "Person deleted", life: 2500 });
  backToList();
}
</script>

<template>
  <section>
    <PageHeader
      title="Biometrics"
      description="Teach the system who your family and friends are, from your own camera footage — face data never leaves this server."
    >
      <template #actions>
        <Button
          v-if="selectedPersonId === null"
          label="Add person"
          icon="pi pi-plus"
          data-testid="open-add-person"
          @click="openAddDialog"
        />
      </template>
    </PageHeader>

    <template v-if="selectedPersonId === null">
      <div
        v-if="loading"
        class="cards"
        data-testid="people-loading"
      >
        <Skeleton
          height="160px"
          border-radius="14px"
        />
      </div>

      <EmptyState
        v-else-if="loadError"
        icon="pi pi-exclamation-triangle"
        title="Couldn't load people"
        description="We weren't able to reach the server. Check your connection and try again."
        data-testid="people-load-error"
      >
        <template #actions>
          <Button
            label="Retry"
            icon="pi pi-refresh"
            severity="secondary"
            outlined
            data-testid="retry-people"
            @click="load"
          />
        </template>
      </EmptyState>

      <EmptyState
        v-else-if="people.length === 0"
        icon="pi pi-id-card"
        title="No one enrolled yet"
        description="Enroll people from real camera frames for the best accuracy — face data never leaves this machine and is never sent to any AI provider."
      >
        <template #actions>
          <Button
            label="Add person"
            icon="pi pi-plus"
            data-testid="open-add-person-empty"
            @click="openAddDialog"
          />
        </template>
      </EmptyState>

      <div
        v-else
        class="cards"
        data-testid="people-grid"
      >
        <article
          v-for="person in people"
          :key="person.id"
          class="person-card"
          :data-testid="`person-card-${person.id}`"
          @click="selectedPersonId = person.id"
        >
          <div class="thumb">
            <img
              v-if="person.has_thumbnail"
              :src="personThumbnailUrl(person.id)"
              :alt="person.name"
            >
            <div
              v-else
              class="thumb-fallback"
            >
              <i
                class="pi pi-user"
                aria-hidden="true"
              />
            </div>
          </div>
          <div class="person-meta">
            <span class="person-name">
              {{ person.name }}
              <i
                v-if="person.never_mark_suspicious"
                class="pi pi-shield trusted-icon"
                data-testid="trusted-icon"
                title="Never marked suspicious"
                aria-label="Never marked suspicious"
              />
            </span>
            <span class="muted">{{ person.face_count }} face sample(s)</span>
          </div>
        </article>
      </div>
    </template>

    <div
      v-else
      class="detail-view"
      data-testid="person-detail-view"
    >
      <Button
        label="Back to people"
        icon="pi pi-arrow-left"
        text
        severity="secondary"
        data-testid="back-to-people"
        @click="backToList"
      />
      <PersonDetailPanel
        :person-id="selectedPersonId"
        @deleted="onPersonDeleted"
      />
    </div>

    <Dialog
      v-model:visible="addDialogVisible"
      modal
      header="Add a person"
      :style="{ width: '28rem', maxWidth: '92vw' }"
      data-testid="add-person-dialog"
    >
      <form
        class="add-form"
        @submit.prevent="submitNewPerson"
      >
        <label
          class="field"
          for="new-person-name"
        >
          <span class="field-label">Name</span>
          <InputText
            id="new-person-name"
            v-model="newPersonName"
            placeholder="e.g. Alex"
            fluid
            autofocus
            data-testid="new-person-name"
          />
        </label>
        <Message
          v-if="createError"
          severity="error"
          :closable="false"
        >
          {{ createError }}
        </Message>
        <div class="form-actions">
          <Button
            type="submit"
            label="Add person"
            :disabled="!newPersonName.trim()"
            :loading="creating"
            data-testid="submit-new-person"
          />
        </div>
      </form>
    </Dialog>
  </section>
</template>

<style scoped>
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 16px;
}

.person-card {
  padding: 16px;
  border-radius: 14px;
  border: 1px solid var(--p-surface-200);
  background: var(--p-surface-0);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  text-align: center;
  cursor: pointer;
  transition:
    border-color 0.15s ease,
    transform 0.15s ease;
}

.blink-dark .person-card {
  border-color: var(--p-surface-800);
  background: color-mix(in srgb, var(--p-surface-900) 60%, transparent);
}

.person-card:hover {
  border-color: var(--p-primary-400);
  transform: translateY(-2px);
}

.thumb {
  width: 88px;
  height: 88px;
  border-radius: 50%;
  overflow: hidden;
  background: var(--p-surface-100);
}

.blink-dark .thumb {
  background: var(--p-surface-800);
}

.thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.thumb-fallback {
  width: 100%;
  height: 100%;
  display: grid;
  place-items: center;
}

.thumb-fallback i {
  font-size: 2rem;
  color: var(--p-surface-400);
}

.person-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.person-name {
  font-size: 0.95rem;
  font-weight: 700;
}

.trusted-icon {
  margin-left: 4px;
  font-size: 0.82em;
  color: var(--p-green-600);
}

.blink-dark .trusted-icon {
  color: var(--p-green-400);
}

.muted {
  font-size: 0.78rem;
  color: var(--p-surface-500);
}

.detail-view {
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding: 20px 24px;
  border-radius: 14px;
  border: 1px solid var(--p-surface-200);
  background: var(--p-surface-0);
}

.blink-dark .detail-view {
  border-color: var(--p-surface-800);
  background: color-mix(in srgb, var(--p-surface-900) 60%, transparent);
}

.add-form {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field-label {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--p-surface-600);
}

.blink-dark .field-label {
  color: var(--p-surface-300);
}

.form-actions {
  display: flex;
  justify-content: flex-end;
}
</style>
