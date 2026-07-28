import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  browseStorageDirectories: vi.fn(),
  createStorageDirectory: vi.fn(),
}));

import { browseStorageDirectories, createStorageDirectory } from "@/api";
import { ApiError } from "@/api/client";
import StorageDirectoryBrowserDialog from "@/components/StorageDirectoryBrowserDialog.vue";
import { makePinia, mountGlobal } from "./helpers";

const mockedBrowse = vi.mocked(browseStorageDirectories);
const mockedCreate = vi.mocked(createStorageDirectory);

function response(path: string, parentPath: string | null, names: string[]) {
  return {
    path,
    parent_path: parentPath,
    directories: names.map((name) => ({ name, path: `${path}/${name}` })),
  };
}

let currentWrapper: VueWrapper | undefined;

beforeEach(() => {
  vi.clearAllMocks();
  mockedBrowse.mockResolvedValue(response("/data/clips", "/data", ["garage", "driveway"]));
});

afterEach(() => {
  currentWrapper?.unmount();
  currentWrapper = undefined;
});

function mountDialog(props: { visible: boolean; initialPath?: string } = { visible: true }) {
  currentWrapper = mount(StorageDirectoryBrowserDialog, {
    props,
    global: mountGlobal(makePinia()),
    attachTo: document.body,
  });
  return currentWrapper;
}

function modal(): HTMLElement {
  return document.body.querySelector('[data-testid="storage-browse-modal"]') as HTMLElement;
}

describe("StorageDirectoryBrowserDialog", () => {
  it("loads the initial path's listing when opened", async () => {
    mountDialog({ visible: true, initialPath: "/data/clips" });
    await flushPromises();
    expect(mockedBrowse).toHaveBeenCalledWith("/data/clips");
    expect(modal().querySelector('[data-testid="storage-browse-current-path"]')?.textContent).toBe(
      "/data/clips",
    );
    const names = [...modal().querySelectorAll("[data-testid^='storage-browse-entry-']")].map(
      (el) => el.textContent?.trim(),
    );
    expect(names).toEqual(["garage", "driveway"]);
  });

  it("does nothing while closed", async () => {
    mountDialog({ visible: false });
    await flushPromises();
    expect(mockedBrowse).not.toHaveBeenCalled();
  });

  it("navigating into a subfolder loads its listing", async () => {
    mockedBrowse.mockResolvedValueOnce(response("/data/clips", "/data", ["garage"]));
    mockedBrowse.mockResolvedValueOnce(response("/data/clips/garage", "/data/clips", []));
    mountDialog({ visible: true, initialPath: "/data/clips" });
    await flushPromises();

    (modal().querySelector('[data-testid="storage-browse-entry-garage"]') as HTMLElement).click();
    await flushPromises();

    expect(mockedBrowse).toHaveBeenLastCalledWith("/data/clips/garage");
    expect(modal().querySelector('[data-testid="storage-browse-current-path"]')?.textContent).toBe(
      "/data/clips/garage",
    );
  });

  it("Up navigates to the parent path, and is disabled once there is none", async () => {
    mockedBrowse.mockResolvedValueOnce(response("/data/clips", "/data", []));
    mockedBrowse.mockResolvedValueOnce(response("/data", null, ["clips"]));
    mountDialog({ visible: true, initialPath: "/data/clips" });
    await flushPromises();

    const up = modal().querySelector('[data-testid="storage-browse-up"]') as HTMLButtonElement;
    expect(up.disabled).toBe(false);
    up.click();
    await flushPromises();

    expect(mockedBrowse).toHaveBeenLastCalledWith("/data");
    expect(
      (modal().querySelector('[data-testid="storage-browse-up"]') as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("shows an error message when listing fails", async () => {
    mockedBrowse.mockRejectedValue(new ApiError(400, "does not exist"));
    mountDialog({ visible: true, initialPath: "/nope" });
    await flushPromises();
    expect(modal().querySelector('[data-testid="storage-browse-error"]')?.textContent?.trim()).toBe(
      "does not exist",
    );
  });

  it("falls back to a generic listing error for non-API failures", async () => {
    mockedBrowse.mockRejectedValue(new TypeError("down"));
    mountDialog({ visible: true, initialPath: "/nope" });
    await flushPromises();
    expect(modal().querySelector('[data-testid="storage-browse-error"]')?.textContent?.trim()).toBe(
      "Could not list this folder.",
    );
  });

  it("disables Create when the name is blank, and creates a folder when submitted", async () => {
    mockedCreate.mockResolvedValue(response("/data/clips/by-camera", "/data/clips", []));
    mountDialog({ visible: true, initialPath: "/data/clips" });
    await flushPromises();

    const createButton = modal().querySelector(
      '[data-testid="storage-browse-create-folder"]',
    ) as HTMLButtonElement;
    expect(createButton.disabled).toBe(true);

    const nameInput = modal().querySelector(
      '[data-testid="storage-browse-new-folder-name"]',
    ) as HTMLInputElement;
    nameInput.value = "by-camera";
    nameInput.dispatchEvent(new Event("input"));
    await flushPromises();
    expect(createButton.disabled).toBe(false);

    modal().querySelector("form")!.dispatchEvent(new Event("submit", { cancelable: true }));
    await flushPromises();

    expect(mockedCreate).toHaveBeenCalledWith("/data/clips", "by-camera");
    expect(modal().querySelector('[data-testid="storage-browse-current-path"]')?.textContent).toBe(
      "/data/clips/by-camera",
    );
  });

  it("shows an error message when folder creation fails", async () => {
    mockedCreate.mockRejectedValue(new ApiError(400, "not writable"));
    mountDialog({ visible: true, initialPath: "/data/clips" });
    await flushPromises();

    const nameInput = modal().querySelector(
      '[data-testid="storage-browse-new-folder-name"]',
    ) as HTMLInputElement;
    nameInput.value = "nope";
    nameInput.dispatchEvent(new Event("input"));
    await flushPromises();
    modal().querySelector("form")!.dispatchEvent(new Event("submit", { cancelable: true }));
    await flushPromises();

    expect(
      modal().querySelector('[data-testid="storage-browse-create-error"]')?.textContent?.trim(),
    ).toBe("not writable");
  });

  it("Select emits the current path and closes", async () => {
    const wrapper = mountDialog({ visible: true, initialPath: "/data/clips" });
    await flushPromises();
    (modal().querySelector('[data-testid="storage-browse-select"]') as HTMLElement).click();
    await flushPromises();
    expect(wrapper.emitted("select")).toEqual([["/data/clips"]]);
    expect(wrapper.emitted("update:visible")).toEqual([[false]]);
  });

  it("Cancel closes without emitting select", async () => {
    const wrapper = mountDialog({ visible: true, initialPath: "/data/clips" });
    await flushPromises();
    (modal().querySelector('[data-testid="storage-browse-cancel"]') as HTMLElement).click();
    await flushPromises();
    expect(wrapper.emitted("select")).toBeUndefined();
    expect(wrapper.emitted("update:visible")).toEqual([[false]]);
  });

  it("passes through the Dialog's own native close (X button / Escape)", async () => {
    const wrapper = mountDialog({ visible: true, initialPath: "/data/clips" });
    await flushPromises();
    await wrapper.findComponent({ name: "Dialog" }).vm.$emit("update:visible", false);
    expect(wrapper.emitted("update:visible")).toEqual([[false]]);
  });

  it("reopening reloads from the initial path and clears any leftover create error", async () => {
    mockedCreate.mockRejectedValue(new ApiError(400, "not writable"));
    const wrapper = mountDialog({ visible: true, initialPath: "/data/clips" });
    await flushPromises();
    const nameInput = modal().querySelector(
      '[data-testid="storage-browse-new-folder-name"]',
    ) as HTMLInputElement;
    nameInput.value = "nope";
    nameInput.dispatchEvent(new Event("input"));
    await flushPromises();
    modal().querySelector("form")!.dispatchEvent(new Event("submit", { cancelable: true }));
    await flushPromises();
    expect(modal().querySelector('[data-testid="storage-browse-create-error"]')).toBeTruthy();

    await wrapper.setProps({ visible: false });
    await wrapper.setProps({ visible: true, initialPath: "/data/clips" });
    await flushPromises();

    expect(modal().querySelector('[data-testid="storage-browse-create-error"]')).toBeFalsy();
    expect(mockedBrowse).toHaveBeenLastCalledWith("/data/clips");
  });
});
