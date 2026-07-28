<script setup lang="ts">
import Button from "primevue/button";
import Dialog from "primevue/dialog";
import InputText from "primevue/inputtext";
import Message from "primevue/message";
import { computed, ref, watch } from "vue";

import {
  ApiError,
  browseCloudFolders,
  createCloudFolder,
  deleteCloudFolder,
  renameCloudFolder,
} from "@/api";
import { useDeleteConfirm } from "@/composables/useDeleteConfirm";

import type { CloudFolderEntry, CloudProvider } from "@/api";

const props = defineProps<{
  visible: boolean;
  provider: CloudProvider;
  providerLabel: string;
}>();

const emit = defineEmits<{
  "update:visible": [value: boolean];
  select: [payload: { id: string; path: string }];
}>();

interface Crumb {
  id: string | null;
  label: string;
}

const ROOT_CRUMB: Crumb = { id: null, label: "Root" };

// Unlike the local storage browser, the backend deliberately doesn't track
// "parent of the current folder" (a Drive/OneDrive folder ID needs an extra
// lookup call to resolve that, which neither list nor create otherwise
// needs) - so this dialog tracks its own breadcrumb trail instead of
// relying on a parent_path in the response.
const trail = ref<Crumb[]>([ROOT_CRUMB]);
const entries = ref<CloudFolderEntry[]>([]);
const loading = ref(false);
const error = ref("");

const newFolderName = ref("");
const creatingFolder = ref(false);
const createError = ref("");

const { confirmDelete } = useDeleteConfirm();
const renamingId = ref<string | null>(null);
const renameValue = ref("");
const renaming = ref(false);
const actionError = ref("");

const currentCrumb = computed(() => trail.value[trail.value.length - 1]!);

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    const response = await browseCloudFolders(props.provider, currentCrumb.value.id ?? undefined);
    entries.value = response.folders;
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : "Could not list folders.";
  } finally {
    loading.value = false;
  }
}

watch(
  () => props.visible,
  (isVisible) => {
    if (isVisible) {
      trail.value = [ROOT_CRUMB];
      newFolderName.value = "";
      createError.value = "";
      renamingId.value = null;
      actionError.value = "";
      void load();
    }
  },
  { immediate: true },
);

function navigateInto(entry: CloudFolderEntry): void {
  trail.value = [...trail.value, { id: entry.id, label: entry.name }];
  void load();
}

function navigateToCrumb(index: number): void {
  // The template also disables the last crumb's button, so this only ever
  // guards against a stale/synthetic click, never a real one.
  /* v8 ignore next */
  if (index === trail.value.length - 1) return;
  trail.value = trail.value.slice(0, index + 1);
  void load();
}

async function createFolder(): Promise<void> {
  createError.value = "";
  creatingFolder.value = true;
  try {
    const response = await createCloudFolder(
      props.provider,
      currentCrumb.value.id,
      newFolderName.value.trim(),
    );
    entries.value = response.folders;
    newFolderName.value = "";
  } catch (caught) {
    createError.value = caught instanceof ApiError ? caught.message : "Could not create this folder.";
  } finally {
    creatingFolder.value = false;
  }
}

function startRename(entry: CloudFolderEntry): void {
  actionError.value = "";
  renamingId.value = entry.id;
  renameValue.value = entry.name;
}

function cancelRename(): void {
  renamingId.value = null;
}

async function confirmRename(): Promise<void> {
  // The confirm button (the only caller) only renders while a rename is in
  // progress, so renamingId is never null here in practice.
  /* v8 ignore next */
  if (!renamingId.value) return;
  actionError.value = "";
  renaming.value = true;
  try {
    await renameCloudFolder(props.provider, renamingId.value, renameValue.value.trim());
    renamingId.value = null;
    await load();
  } catch (caught) {
    actionError.value = caught instanceof ApiError ? caught.message : "Could not rename this folder.";
  } finally {
    renaming.value = false;
  }
}

function deleteEntry(entry: CloudFolderEntry): void {
  confirmDelete({
    header: "Delete folder",
    message: `Delete "${entry.name}"?${
      props.provider === "s3"
        ? " This only works if the folder is empty, and can't be undone."
        : " It'll be moved to your provider's trash/recycle bin."
    }`,
    onAccept: () => void performDelete(entry),
  });
}

async function performDelete(entry: CloudFolderEntry): Promise<void> {
  actionError.value = "";
  try {
    await deleteCloudFolder(props.provider, entry.id);
    await load();
  } catch (caught) {
    actionError.value = caught instanceof ApiError ? caught.message : "Could not delete this folder.";
  }
}

function selectCurrent(): void {
  // Some providers (S3, Google Drive) key folders by an id that's directly
  // usable as the stored setting; OneDrive's upload path addresses folders
  // by name path, not by the opaque item id browsing returns - so callers
  // get both and pick whichever their provider's field actually stores.
  const path = trail.value
    .slice(1)
    .map((crumb) => crumb.label)
    .join("/");
  emit("select", { id: currentCrumb.value.id ?? "", path });
  emit("update:visible", false);
}
</script>

<template>
  <Dialog
    :visible="visible"
    :header="`Choose a folder in ${providerLabel}`"
    modal
    :style="{ width: '32rem' }"
    :breakpoints="{ '640px': '92vw' }"
    data-testid="cloud-browse-modal"
    @update:visible="(value: boolean) => emit('update:visible', value)"
  >
    <nav
      class="breadcrumbs"
      aria-label="Folder path"
    >
      <template
        v-for="(crumb, index) in trail"
        :key="index"
      >
        <button
          type="button"
          class="crumb"
          :class="{ current: index === trail.length - 1 }"
          :disabled="index === trail.length - 1"
          :data-testid="`cloud-browse-crumb-${index}`"
          @click="navigateToCrumb(index)"
        >
          {{ crumb.label }}
        </button>
        <span
          v-if="index < trail.length - 1"
          class="crumb-sep"
          aria-hidden="true"
        >/</span>
      </template>
    </nav>

    <Message
      v-if="error"
      severity="error"
      :closable="false"
      data-testid="cloud-browse-error"
    >
      {{ error }}
    </Message>

    <ul
      v-else
      class="entry-list"
      data-testid="cloud-browse-entries"
    >
      <li
        v-if="!loading && entries.length === 0"
        class="muted empty"
      >
        No subfolders here yet.
      </li>
      <li
        v-for="entry in entries"
        :key="entry.id"
        class="entry"
      >
        <form
          v-if="renamingId === entry.id"
          class="rename-row"
          @submit.prevent="confirmRename"
        >
          <InputText
            v-model="renameValue"
            autofocus
            fluid
            :data-testid="`cloud-browse-rename-input-${entry.name}`"
          />
          <Button
            type="submit"
            icon="pi pi-check"
            text
            rounded
            severity="success"
            aria-label="Confirm rename"
            :disabled="!renameValue.trim()"
            :loading="renaming"
            :data-testid="`cloud-browse-rename-confirm-${entry.name}`"
          />
          <Button
            type="button"
            icon="pi pi-times"
            text
            rounded
            severity="secondary"
            aria-label="Cancel rename"
            :data-testid="`cloud-browse-rename-cancel-${entry.name}`"
            @click="cancelRename"
          />
        </form>
        <template v-else>
          <button
            type="button"
            class="entry-button"
            :data-testid="`cloud-browse-entry-${entry.name}`"
            @click="navigateInto(entry)"
          >
            <i
              class="pi pi-folder"
              aria-hidden="true"
            />
            {{ entry.name }}
          </button>
          <div class="entry-actions">
            <Button
              icon="pi pi-pencil"
              text
              rounded
              size="small"
              :aria-label="`Rename ${entry.name}`"
              :data-testid="`cloud-browse-rename-${entry.name}`"
              @click="startRename(entry)"
            />
            <Button
              icon="pi pi-trash"
              text
              rounded
              size="small"
              severity="danger"
              :aria-label="`Delete ${entry.name}`"
              :data-testid="`cloud-browse-delete-${entry.name}`"
              @click="deleteEntry(entry)"
            />
          </div>
        </template>
      </li>
    </ul>

    <Message
      v-if="actionError"
      severity="error"
      :closable="false"
      data-testid="cloud-browse-action-error"
    >
      {{ actionError }}
    </Message>

    <form
      class="new-folder-row"
      @submit.prevent="createFolder"
    >
      <InputText
        v-model="newFolderName"
        placeholder="New folder name"
        fluid
        data-testid="cloud-browse-new-folder-name"
      />
      <Button
        type="submit"
        label="Create"
        severity="secondary"
        outlined
        :disabled="!newFolderName.trim()"
        :loading="creatingFolder"
        data-testid="cloud-browse-create-folder"
      />
    </form>
    <Message
      v-if="createError"
      severity="error"
      :closable="false"
      data-testid="cloud-browse-create-error"
    >
      {{ createError }}
    </Message>

    <div class="panel-actions">
      <Button
        label="Cancel"
        severity="secondary"
        outlined
        data-testid="cloud-browse-cancel"
        @click="emit('update:visible', false)"
      />
      <Button
        label="Select this folder"
        data-testid="cloud-browse-select"
        @click="selectCurrent"
      />
    </div>
  </Dialog>
</template>

<style scoped>
.breadcrumbs {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  margin-bottom: 14px;
  font-size: 0.82rem;
}

.crumb {
  padding: 3px 6px;
  border: none;
  border-radius: 6px;
  background: none;
  color: var(--p-primary-500);
  font: inherit;
  cursor: pointer;
}

.crumb:hover:not(:disabled) {
  background: var(--p-surface-100);
}

.blink-dark .crumb:hover:not(:disabled) {
  background: color-mix(in srgb, var(--p-surface-800) 70%, transparent);
}

.crumb.current {
  color: var(--p-surface-700);
  font-weight: 600;
  cursor: default;
}

.blink-dark .crumb.current {
  color: var(--p-surface-200);
}

.crumb-sep {
  color: var(--p-surface-400);
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
  font-size: 0.82rem;
  color: var(--p-surface-500);
}

.entry {
  display: flex;
  align-items: center;
  gap: 4px;
}

.entry-button {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  min-width: 0;
  padding: 9px 12px;
  border: none;
  background: none;
  text-align: left;
  font-size: 0.88rem;
  cursor: pointer;
  color: inherit;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.entry-button:hover {
  background: var(--p-surface-100);
}

.blink-dark .entry-button:hover {
  background: color-mix(in srgb, var(--p-surface-800) 70%, transparent);
}

.entry-actions {
  display: flex;
  gap: 2px;
  padding-right: 6px;
}

.rename-row {
  display: flex;
  align-items: center;
  gap: 4px;
  width: 100%;
  padding: 4px 8px;
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
