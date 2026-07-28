import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  browseCloudFolders: vi.fn(),
  createCloudFolder: vi.fn(),
  renameCloudFolder: vi.fn(),
  deleteCloudFolder: vi.fn(),
}));

const confirmRequire = vi.fn();
vi.mock("primevue/useconfirm", () => ({ useConfirm: () => ({ require: confirmRequire }) }));

import {
  browseCloudFolders,
  createCloudFolder,
  deleteCloudFolder,
  renameCloudFolder,
} from "@/api";
import { ApiError } from "@/api/client";
import CloudFolderBrowserDialog from "@/components/CloudFolderBrowserDialog.vue";
import { makePinia, mountGlobal } from "./helpers";

const mockedBrowse = vi.mocked(browseCloudFolders);
const mockedCreate = vi.mocked(createCloudFolder);
const mockedRename = vi.mocked(renameCloudFolder);
const mockedDelete = vi.mocked(deleteCloudFolder);

function response(entries: Array<{ id: string; name: string }>) {
  return { folders: entries };
}

let currentWrapper: VueWrapper | undefined;

beforeEach(() => {
  vi.clearAllMocks();
  mockedBrowse.mockResolvedValue(response([{ id: "clips-id", name: "Clips" }]));
});

afterEach(() => {
  currentWrapper?.unmount();
  currentWrapper = undefined;
});

function mountDialog(
  props: { visible: boolean; provider?: "s3" | "google_drive" | "onedrive"; providerLabel?: string } = {
    visible: true,
  },
) {
  currentWrapper = mount(CloudFolderBrowserDialog, {
    props: {
      provider: "s3",
      providerLabel: "Amazon S3",
      ...props,
    },
    global: mountGlobal(makePinia()),
    attachTo: document.body,
  });
  return currentWrapper;
}

function modal(): HTMLElement {
  return document.body.querySelector('[data-testid="cloud-browse-modal"]') as HTMLElement;
}

function entryNames(): (string | undefined)[] {
  return [...modal().querySelectorAll("[data-testid^='cloud-browse-entry-']")].map((el) =>
    el.textContent?.trim(),
  );
}

describe("CloudFolderBrowserDialog", () => {
  it("loads the root listing when opened", async () => {
    mountDialog({ visible: true });
    await flushPromises();
    expect(mockedBrowse).toHaveBeenCalledWith("s3", undefined);
    expect(modal().querySelector('[data-testid="cloud-browse-crumb-0"]')?.textContent?.trim()).toBe(
      "Root",
    );
    expect(entryNames()).toEqual(["Clips"]);
  });

  it("does nothing while closed", async () => {
    mountDialog({ visible: false });
    await flushPromises();
    expect(mockedBrowse).not.toHaveBeenCalled();
  });

  it("shows a header naming the provider", async () => {
    mountDialog({ visible: true, provider: "google_drive", providerLabel: "Google Drive" });
    await flushPromises();
    expect(modal().textContent).toContain("Choose a folder in Google Drive");
  });

  it("shows a message when there are no subfolders", async () => {
    mockedBrowse.mockResolvedValue(response([]));
    mountDialog({ visible: true });
    await flushPromises();
    expect(modal().textContent).toContain("No subfolders here yet.");
  });

  it("navigating into a subfolder appends a breadcrumb and reloads at that folder", async () => {
    mockedBrowse.mockResolvedValueOnce(response([{ id: "clips-id", name: "Clips" }]));
    mockedBrowse.mockResolvedValueOnce(response([{ id: "2026-id", name: "2026" }]));
    mountDialog({ visible: true });
    await flushPromises();

    (modal().querySelector('[data-testid="cloud-browse-entry-Clips"]') as HTMLElement).click();
    await flushPromises();

    expect(mockedBrowse).toHaveBeenLastCalledWith("s3", "clips-id");
    expect(modal().querySelector('[data-testid="cloud-browse-crumb-1"]')?.textContent?.trim()).toBe(
      "Clips",
    );
    expect(entryNames()).toEqual(["2026"]);
  });

  it("the current crumb is not clickable, earlier crumbs are", async () => {
    mountDialog({ visible: true });
    await flushPromises();
    const rootCrumb = modal().querySelector(
      '[data-testid="cloud-browse-crumb-0"]',
    ) as HTMLButtonElement;
    expect(rootCrumb.disabled).toBe(true);
  });

  it("navigating back to an earlier breadcrumb trims the trail and reloads", async () => {
    mockedBrowse.mockResolvedValueOnce(response([{ id: "clips-id", name: "Clips" }]));
    mockedBrowse.mockResolvedValueOnce(response([{ id: "2026-id", name: "2026" }]));
    mockedBrowse.mockResolvedValueOnce(response([{ id: "clips-id", name: "Clips" }]));
    mountDialog({ visible: true });
    await flushPromises();
    (modal().querySelector('[data-testid="cloud-browse-entry-Clips"]') as HTMLElement).click();
    await flushPromises();

    (modal().querySelector('[data-testid="cloud-browse-crumb-0"]') as HTMLElement).click();
    await flushPromises();

    expect(mockedBrowse).toHaveBeenLastCalledWith("s3", undefined);
    expect(modal().querySelector('[data-testid="cloud-browse-crumb-1"]')).toBeFalsy();
    const rootCrumb = modal().querySelector(
      '[data-testid="cloud-browse-crumb-0"]',
    ) as HTMLButtonElement;
    expect(rootCrumb.disabled).toBe(true);
  });

  it("shows an error message when listing fails", async () => {
    mockedBrowse.mockRejectedValue(new ApiError(400, "S3 isn't connected yet."));
    mountDialog({ visible: true });
    await flushPromises();
    expect(modal().querySelector('[data-testid="cloud-browse-error"]')?.textContent?.trim()).toBe(
      "S3 isn't connected yet.",
    );
  });

  it("falls back to a generic listing error for non-API failures", async () => {
    mockedBrowse.mockRejectedValue(new TypeError("down"));
    mountDialog({ visible: true });
    await flushPromises();
    expect(modal().querySelector('[data-testid="cloud-browse-error"]')?.textContent?.trim()).toBe(
      "Could not list folders.",
    );
  });

  it("disables Create when the name is blank, and creates a folder when submitted", async () => {
    mockedCreate.mockResolvedValue(
      response([
        { id: "clips-id", name: "Clips" },
        { id: "archive-id", name: "Archive" },
      ]),
    );
    mountDialog({ visible: true });
    await flushPromises();

    const createButton = modal().querySelector(
      '[data-testid="cloud-browse-create-folder"]',
    ) as HTMLButtonElement;
    expect(createButton.disabled).toBe(true);

    const nameInput = modal().querySelector(
      '[data-testid="cloud-browse-new-folder-name"]',
    ) as HTMLInputElement;
    nameInput.value = "Archive";
    nameInput.dispatchEvent(new Event("input"));
    await flushPromises();
    expect(createButton.disabled).toBe(false);

    modal().querySelector("form")!.dispatchEvent(new Event("submit", { cancelable: true }));
    await flushPromises();

    expect(mockedCreate).toHaveBeenCalledWith("s3", null, "Archive");
    expect(entryNames()).toEqual(["Clips", "Archive"]);
    expect((nameInput as HTMLInputElement).value).toBe("");
  });

  it("shows an error message when folder creation fails", async () => {
    mockedCreate.mockRejectedValue(new ApiError(400, "A folder with that name already exists."));
    mountDialog({ visible: true });
    await flushPromises();

    const nameInput = modal().querySelector(
      '[data-testid="cloud-browse-new-folder-name"]',
    ) as HTMLInputElement;
    nameInput.value = "Clips";
    nameInput.dispatchEvent(new Event("input"));
    await flushPromises();
    modal().querySelector("form")!.dispatchEvent(new Event("submit", { cancelable: true }));
    await flushPromises();

    expect(
      modal().querySelector('[data-testid="cloud-browse-create-error"]')?.textContent?.trim(),
    ).toBe("A folder with that name already exists.");
  });

  it("falls back to a generic error for a non-API folder creation failure", async () => {
    mockedCreate.mockRejectedValue(new TypeError("down"));
    mountDialog({ visible: true });
    await flushPromises();

    const nameInput = modal().querySelector(
      '[data-testid="cloud-browse-new-folder-name"]',
    ) as HTMLInputElement;
    nameInput.value = "Clips";
    nameInput.dispatchEvent(new Event("input"));
    await flushPromises();
    modal().querySelector("form")!.dispatchEvent(new Event("submit", { cancelable: true }));
    await flushPromises();

    expect(
      modal().querySelector('[data-testid="cloud-browse-create-error"]')?.textContent?.trim(),
    ).toBe("Could not create this folder.");
  });

  it("rename shows an inline input pre-filled with the current name", async () => {
    mountDialog({ visible: true });
    await flushPromises();
    (modal().querySelector('[data-testid="cloud-browse-rename-Clips"]') as HTMLElement).click();
    await flushPromises();
    const input = modal().querySelector(
      '[data-testid="cloud-browse-rename-input-Clips"]',
    ) as HTMLInputElement;
    expect(input.value).toBe("Clips");
    expect(modal().querySelector('[data-testid="cloud-browse-entry-Clips"]')).toBeNull();
  });

  it("cancelling a rename restores the plain entry", async () => {
    mountDialog({ visible: true });
    await flushPromises();
    (modal().querySelector('[data-testid="cloud-browse-rename-Clips"]') as HTMLElement).click();
    await flushPromises();
    (
      modal().querySelector('[data-testid="cloud-browse-rename-cancel-Clips"]') as HTMLElement
    ).click();
    await flushPromises();
    expect(modal().querySelector('[data-testid="cloud-browse-entry-Clips"]')).toBeTruthy();
    expect(mockedRename).not.toHaveBeenCalled();
  });

  it("confirming a rename saves the new name and reloads the current level", async () => {
    mockedRename.mockResolvedValue(undefined);
    mockedBrowse.mockResolvedValueOnce(response([{ id: "clips-id", name: "Clips" }]));
    mockedBrowse.mockResolvedValueOnce(response([{ id: "clips-id", name: "Archive" }]));
    mountDialog({ visible: true });
    await flushPromises();
    (modal().querySelector('[data-testid="cloud-browse-rename-Clips"]') as HTMLElement).click();
    await flushPromises();
    const input = modal().querySelector(
      '[data-testid="cloud-browse-rename-input-Clips"]',
    ) as HTMLInputElement;
    input.value = "Archive";
    input.dispatchEvent(new Event("input"));
    await flushPromises();
    modal().querySelector('[data-testid="cloud-browse-rename-input-Clips"]')?.closest("form")
      ?.dispatchEvent(new Event("submit", { cancelable: true }));
    await flushPromises();

    expect(mockedRename).toHaveBeenCalledWith("s3", "clips-id", "Archive");
    expect(entryNames()).toEqual(["Archive"]);
  });

  it("shows an error message when a rename fails", async () => {
    mockedRename.mockRejectedValue(new ApiError(400, "already exists"));
    mountDialog({ visible: true });
    await flushPromises();
    (modal().querySelector('[data-testid="cloud-browse-rename-Clips"]') as HTMLElement).click();
    await flushPromises();
    modal().querySelector('[data-testid="cloud-browse-rename-input-Clips"]')?.closest("form")
      ?.dispatchEvent(new Event("submit", { cancelable: true }));
    await flushPromises();
    expect(
      modal().querySelector('[data-testid="cloud-browse-action-error"]')?.textContent?.trim(),
    ).toBe("already exists");
  });

  it("falls back to a generic error for a non-API rename failure", async () => {
    mockedRename.mockRejectedValue(new TypeError("down"));
    mountDialog({ visible: true });
    await flushPromises();
    (modal().querySelector('[data-testid="cloud-browse-rename-Clips"]') as HTMLElement).click();
    await flushPromises();
    modal().querySelector('[data-testid="cloud-browse-rename-input-Clips"]')?.closest("form")
      ?.dispatchEvent(new Event("submit", { cancelable: true }));
    await flushPromises();
    expect(
      modal().querySelector('[data-testid="cloud-browse-action-error"]')?.textContent?.trim(),
    ).toBe("Could not rename this folder.");
  });

  it("delete asks for confirmation naming the folder, with S3-specific empty-only wording", async () => {
    mountDialog({ visible: true, provider: "s3" });
    await flushPromises();
    (modal().querySelector('[data-testid="cloud-browse-delete-Clips"]') as HTMLElement).click();
    await flushPromises();
    const options = confirmRequire.mock.calls.at(-1)?.[0] as { header: string; message: string };
    expect(options.header).toBe("Delete folder");
    expect(options.message).toContain("Clips");
    expect(options.message).toContain("empty");
  });

  it("delete mentions the trash/recycle bin for Google Drive and OneDrive", async () => {
    mountDialog({ visible: true, provider: "google_drive", providerLabel: "Google Drive" });
    await flushPromises();
    (modal().querySelector('[data-testid="cloud-browse-delete-Clips"]') as HTMLElement).click();
    await flushPromises();
    const options = confirmRequire.mock.calls.at(-1)?.[0] as { message: string };
    expect(options.message).toContain("trash");
  });

  it("confirming delete removes the folder and reloads the current level", async () => {
    mockedDelete.mockResolvedValue(undefined);
    mockedBrowse.mockResolvedValueOnce(response([{ id: "clips-id", name: "Clips" }]));
    mockedBrowse.mockResolvedValueOnce(response([]));
    mountDialog({ visible: true });
    await flushPromises();
    (modal().querySelector('[data-testid="cloud-browse-delete-Clips"]') as HTMLElement).click();
    await flushPromises();
    const options = confirmRequire.mock.calls.at(-1)?.[0] as { accept: () => void };
    options.accept();
    await flushPromises();

    expect(mockedDelete).toHaveBeenCalledWith("s3", "clips-id");
    expect(modal().querySelector('[data-testid="cloud-browse-entry-Clips"]')).toBeNull();
  });

  it("shows an error message when delete fails", async () => {
    mockedDelete.mockRejectedValue(new ApiError(400, "not empty"));
    mountDialog({ visible: true });
    await flushPromises();
    (modal().querySelector('[data-testid="cloud-browse-delete-Clips"]') as HTMLElement).click();
    await flushPromises();
    const options = confirmRequire.mock.calls.at(-1)?.[0] as { accept: () => void };
    options.accept();
    await flushPromises();
    expect(
      modal().querySelector('[data-testid="cloud-browse-action-error"]')?.textContent?.trim(),
    ).toBe("not empty");
  });

  it("falls back to a generic error for a non-API delete failure", async () => {
    mockedDelete.mockRejectedValue(new TypeError("down"));
    mountDialog({ visible: true });
    await flushPromises();
    (modal().querySelector('[data-testid="cloud-browse-delete-Clips"]') as HTMLElement).click();
    await flushPromises();
    const options = confirmRequire.mock.calls.at(-1)?.[0] as { accept: () => void };
    options.accept();
    await flushPromises();
    expect(
      modal().querySelector('[data-testid="cloud-browse-action-error"]')?.textContent?.trim(),
    ).toBe("Could not delete this folder.");
  });

  it("reopening clears any leftover rename/delete action error", async () => {
    mockedDelete.mockRejectedValue(new ApiError(400, "not empty"));
    const wrapper = mountDialog({ visible: true });
    await flushPromises();
    (modal().querySelector('[data-testid="cloud-browse-delete-Clips"]') as HTMLElement).click();
    await flushPromises();
    (confirmRequire.mock.calls.at(-1)?.[0] as { accept: () => void }).accept();
    await flushPromises();
    expect(modal().querySelector('[data-testid="cloud-browse-action-error"]')).toBeTruthy();

    await wrapper.setProps({ visible: false });
    await wrapper.setProps({ visible: true });
    await flushPromises();
    expect(modal().querySelector('[data-testid="cloud-browse-action-error"]')).toBeFalsy();
  });

  it("Select at the root emits an empty id and path, and closes", async () => {
    const wrapper = mountDialog({ visible: true });
    await flushPromises();
    (modal().querySelector('[data-testid="cloud-browse-select"]') as HTMLElement).click();
    await flushPromises();
    expect(wrapper.emitted("select")).toEqual([[{ id: "", path: "" }]]);
    expect(wrapper.emitted("update:visible")).toEqual([[false]]);
  });

  it("Select after navigating in emits the folder's id and its composed breadcrumb path", async () => {
    mockedBrowse.mockResolvedValueOnce(response([{ id: "clips-id", name: "Clips" }]));
    mockedBrowse.mockResolvedValueOnce(response([{ id: "2026-id", name: "2026" }]));
    const wrapper = mountDialog({ visible: true });
    await flushPromises();
    (modal().querySelector('[data-testid="cloud-browse-entry-Clips"]') as HTMLElement).click();
    await flushPromises();

    (modal().querySelector('[data-testid="cloud-browse-select"]') as HTMLElement).click();
    await flushPromises();

    expect(wrapper.emitted("select")).toEqual([[{ id: "clips-id", path: "Clips" }]]);
  });

  it("Cancel closes without emitting select", async () => {
    const wrapper = mountDialog({ visible: true });
    await flushPromises();
    (modal().querySelector('[data-testid="cloud-browse-cancel"]') as HTMLElement).click();
    await flushPromises();
    expect(wrapper.emitted("select")).toBeUndefined();
    expect(wrapper.emitted("update:visible")).toEqual([[false]]);
  });

  it("passes through the Dialog's own native close (X button / Escape)", async () => {
    const wrapper = mountDialog({ visible: true });
    await flushPromises();
    await wrapper.findComponent({ name: "Dialog" }).vm.$emit("update:visible", false);
    expect(wrapper.emitted("update:visible")).toEqual([[false]]);
  });

  it("reopening resets the trail to Root and clears any leftover create error", async () => {
    mockedCreate.mockRejectedValue(new ApiError(400, "nope"));
    mockedBrowse.mockResolvedValueOnce(response([{ id: "clips-id", name: "Clips" }]));
    mockedBrowse.mockResolvedValueOnce(response([{ id: "2026-id", name: "2026" }]));
    const wrapper = mountDialog({ visible: true });
    await flushPromises();
    (modal().querySelector('[data-testid="cloud-browse-entry-Clips"]') as HTMLElement).click();
    await flushPromises();

    const nameInput = modal().querySelector(
      '[data-testid="cloud-browse-new-folder-name"]',
    ) as HTMLInputElement;
    nameInput.value = "nope";
    nameInput.dispatchEvent(new Event("input"));
    await flushPromises();
    modal().querySelector("form")!.dispatchEvent(new Event("submit", { cancelable: true }));
    await flushPromises();
    expect(modal().querySelector('[data-testid="cloud-browse-create-error"]')).toBeTruthy();

    mockedBrowse.mockResolvedValueOnce(response([{ id: "clips-id", name: "Clips" }]));
    await wrapper.setProps({ visible: false });
    await wrapper.setProps({ visible: true });
    await flushPromises();

    expect(modal().querySelector('[data-testid="cloud-browse-create-error"]')).toBeFalsy();
    expect(modal().querySelector('[data-testid="cloud-browse-crumb-1"]')).toBeFalsy();
    expect(mockedBrowse).toHaveBeenLastCalledWith("s3", undefined);
  });
});
