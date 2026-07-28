<script setup lang="ts">
import Button from "primevue/button";
import Dialog from "primevue/dialog";
import InputText from "primevue/inputtext";
import Message from "primevue/message";
import { ref, watch } from "vue";

import { ApiError, browseStorageDirectories, createStorageDirectory } from "@/api";

import type { StorageBrowseEntry } from "@/api";

const props = defineProps<{
  visible: boolean;
  initialPath?: string;
}>();

const emit = defineEmits<{
  "update:visible": [value: boolean];
  select: [path: string];
}>();

const currentPath = ref("");
const parentPath = ref<string | null>(null);
const entries = ref<StorageBrowseEntry[]>([]);
const loading = ref(false);
const error = ref("");

const newFolderName = ref("");
const creatingFolder = ref(false);
const createError = ref("");

async function loadPath(path?: string): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    const response = await browseStorageDirectories(path);
    currentPath.value = response.path;
    parentPath.value = response.parent_path;
    entries.value = response.directories;
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : "Could not list this folder.";
  } finally {
    loading.value = false;
  }
}

watch(
  () => props.visible,
  (isVisible) => {
    if (isVisible) {
      newFolderName.value = "";
      createError.value = "";
      void loadPath(props.initialPath);
    }
  },
  { immediate: true },
);

function navigateInto(entry: StorageBrowseEntry): void {
  void loadPath(entry.path);
}

function navigateUp(): void {
  // The template also disables the Up button once there's no parent, so
  // this only ever guards against a stale/synthetic click, never a real one.
  /* v8 ignore next 3 */
  if (parentPath.value) {
    void loadPath(parentPath.value);
  }
}

async function createFolder(): Promise<void> {
  createError.value = "";
  creatingFolder.value = true;
  try {
    const response = await createStorageDirectory(currentPath.value, newFolderName.value.trim());
    currentPath.value = response.path;
    parentPath.value = response.parent_path;
    entries.value = response.directories;
    newFolderName.value = "";
  } catch (caught) {
    createError.value = caught instanceof ApiError ? caught.message : "Could not create this folder.";
  } finally {
    creatingFolder.value = false;
  }
}

function selectCurrent(): void {
  emit("select", currentPath.value);
  emit("update:visible", false);
}
</script>

<template>
  <Dialog
    :visible="visible"
    header="Choose a storage folder"
    modal
    :style="{ width: '32rem' }"
    :breakpoints="{ '640px': '92vw' }"
    data-testid="storage-browse-modal"
    @update:visible="(value: boolean) => emit('update:visible', value)"
  >
    <p class="muted">
      Browsing folders inside this server's clip storage mount - not your whole computer.
    </p>

    <div class="path-row">
      <Button
        icon="pi pi-arrow-up"
        text
        size="small"
        :disabled="!parentPath || loading"
        data-testid="storage-browse-up"
        @click="navigateUp"
      />
      <code
        class="current-path"
        data-testid="storage-browse-current-path"
      >{{ currentPath }}</code>
    </div>

    <Message
      v-if="error"
      severity="error"
      :closable="false"
      data-testid="storage-browse-error"
    >
      {{ error }}
    </Message>

    <ul
      v-else
      class="entry-list"
      data-testid="storage-browse-entries"
    >
      <li
        v-if="!loading && entries.length === 0"
        class="muted empty"
      >
        No subfolders here yet.
      </li>
      <li
        v-for="entry in entries"
        :key="entry.path"
        class="entry"
      >
        <button
          type="button"
          class="entry-button"
          :data-testid="`storage-browse-entry-${entry.name}`"
          @click="navigateInto(entry)"
        >
          <i
            class="pi pi-folder"
            aria-hidden="true"
          />
          {{ entry.name }}
        </button>
      </li>
    </ul>

    <form
      class="new-folder-row"
      @submit.prevent="createFolder"
    >
      <InputText
        v-model="newFolderName"
        placeholder="New folder name"
        fluid
        data-testid="storage-browse-new-folder-name"
      />
      <Button
        type="submit"
        label="Create"
        severity="secondary"
        outlined
        :disabled="!newFolderName.trim()"
        :loading="creatingFolder"
        data-testid="storage-browse-create-folder"
      />
    </form>
    <Message
      v-if="createError"
      severity="error"
      :closable="false"
      data-testid="storage-browse-create-error"
    >
      {{ createError }}
    </Message>

    <div class="panel-actions">
      <Button
        label="Cancel"
        severity="secondary"
        outlined
        data-testid="storage-browse-cancel"
        @click="emit('update:visible', false)"
      />
      <Button
        label="Select this folder"
        data-testid="storage-browse-select"
        @click="selectCurrent"
      />
    </div>
  </Dialog>
</template>

<style scoped>
.muted {
  font-size: 0.82rem;
  color: var(--p-surface-500);
  margin: 0 0 14px;
}

.path-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.current-path {
  font-size: 0.82rem;
  padding: 4px 8px;
  border-radius: 6px;
  background: var(--p-surface-100);
  overflow-x: auto;
  white-space: nowrap;
}

.blink-dark .current-path {
  background: color-mix(in srgb, var(--p-surface-800) 60%, transparent);
}

.entry-list {
  list-style: none;
  margin: 0 0 16px;
  padding: 0;
  max-height: 260px;
  overflow-y: auto;
  border: 1px solid var(--p-surface-200);
  border-radius: 8px;
}

.blink-dark .entry-list {
  border-color: var(--p-surface-800);
}

.entry-list .empty {
  padding: 14px;
}

.entry-button {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 9px 12px;
  border: none;
  background: none;
  text-align: left;
  font-size: 0.88rem;
  cursor: pointer;
  color: inherit;
}

.entry-button:hover {
  background: var(--p-surface-100);
}

.blink-dark .entry-button:hover {
  background: color-mix(in srgb, var(--p-surface-800) 70%, transparent);
}

.new-folder-row {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
}

.panel-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
}
</style>
