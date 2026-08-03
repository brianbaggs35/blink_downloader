import { flushPromises, mount } from "@vue/test-utils";
import Select from "primevue/select";
import ToggleSwitch from "primevue/toggleswitch";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/client";
import SetupView from "@/views/SetupView.vue";
import { fakeBlinkStatus, fakeUser, makePinia, makeRouter, mountGlobal } from "./helpers";

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  runSetup: vi.fn(),
  login: vi.fn(),
  getMe: vi.fn(),
  getBlinkStatus: vi.fn(),
  triggerBlinkSync: vi.fn(),
  listCameras: vi.fn(),
  updateCamera: vi.fn(),
  getStorageSettings: vi.fn(),
  updateStorageSettings: vi.fn(),
  browseStorageDirectories: vi.fn(),
  createStorageDirectory: vi.fn(),
}));

const toastAdd = vi.fn();
vi.mock("primevue/usetoast", () => ({ useToast: () => ({ add: toastAdd }) }));

import { beforeEach } from "vitest";

import {
  browseStorageDirectories,
  getBlinkStatus,
  getMe,
  getStorageSettings,
  listCameras,
  login,
  runSetup,
  triggerBlinkSync,
  updateCamera,
  updateStorageSettings,
} from "@/api";

const mockedSetup = vi.mocked(runSetup);
const mockedLogin = vi.mocked(login);
const mockedMe = vi.mocked(getMe);
const mockedBlinkStatus = vi.mocked(getBlinkStatus);
const mockedSyncNow = vi.mocked(triggerBlinkSync);
const mockedListCameras = vi.mocked(listCameras);
const mockedUpdateCamera = vi.mocked(updateCamera);
const mockedGetStorage = vi.mocked(getStorageSettings);
const mockedUpdateStorage = vi.mocked(updateStorageSettings);
const mockedBrowseStorage = vi.mocked(browseStorageDirectories);

function unlinkedStatus() {
  return fakeBlinkStatus();
}

function linkedStatus() {
  return fakeBlinkStatus({ linked: true, status: "active", camera_count: 1 });
}

beforeEach(() => {
  vi.clearAllMocks();
  mockedBlinkStatus.mockResolvedValue(unlinkedStatus());
  mockedSyncNow.mockResolvedValue({ status: "sync_started" });
  mockedListCameras.mockResolvedValue([]);
  mockedGetStorage.mockResolvedValue({
    storage_dir: "/data/clips",
    is_default: true,
    local_storage_quota_bytes: null,
  });
});

async function mountSetup() {
  const router = makeRouter();
  await router.push("/setup");
  const wrapper = mount(SetupView, {
    global: mountGlobal(makePinia(), router),
    attachTo: document.body,
  });
  await flushPromises();
  return { wrapper, router };
}

async function fillAccountForm(
  wrapper: Awaited<ReturnType<typeof mountSetup>>["wrapper"],
  password: string,
  confirm: string,
) {
  await wrapper.find('[data-testid="display-name"]').setValue("Brian");
  await wrapper.find('[data-testid="email"]').setValue("admin@example.com");
  await wrapper.find('[data-testid="password"] input').setValue(password);
  await wrapper.find('[data-testid="confirm"] input').setValue(confirm);
  await wrapper.find("form").trigger("submit");
  await flushPromises();
}

async function completeAccountStep(wrapper: Awaited<ReturnType<typeof mountSetup>>["wrapper"]) {
  mockedSetup.mockResolvedValue(fakeUser);
  mockedLogin.mockResolvedValue(undefined);
  mockedMe.mockResolvedValue(fakeUser);
  await fillAccountForm(wrapper, "a-long-enough-password", "a-long-enough-password");
}

async function completeStorageStep(wrapper: Awaited<ReturnType<typeof mountSetup>>["wrapper"]) {
  await wrapper.find('[data-testid="storage-step-continue"]').trigger("click");
  await flushPromises();
}

describe("SetupView — account step", () => {
  it("rejects short passwords client-side", async () => {
    const { wrapper } = await mountSetup();
    await fillAccountForm(wrapper, "short", "short");
    expect(wrapper.find('[data-testid="setup-error"]').text()).toContain("at least 12");
    expect(mockedSetup).not.toHaveBeenCalled();
  });

  it("rejects mismatched passwords client-side", async () => {
    const { wrapper } = await mountSetup();
    await fillAccountForm(wrapper, "a-long-enough-password", "a-different-password");
    expect(wrapper.find('[data-testid="setup-error"]').text()).toBe("Passwords do not match.");
    expect(mockedSetup).not.toHaveBeenCalled();
  });

  it("creates the admin, signs in, and advances to the storage step", async () => {
    const { wrapper, router } = await mountSetup();
    await completeAccountStep(wrapper);
    expect(mockedSetup).toHaveBeenCalledWith(
      expect.objectContaining({
        email: "admin@example.com",
        password: "a-long-enough-password",
        display_name: "Brian",
      }),
    );
    expect(wrapper.find('[data-testid="setup-storage-browse"]').exists()).toBe(true);
    // Setup itself never navigates the browser away - only "Go to Library" does.
    expect(router.currentRoute.value.name).toBe("setup");
  });

  it("pre-selects the browser's own detected timezone", async () => {
    const { wrapper } = await mountSetup();
    await completeAccountStep(wrapper);
    expect(mockedSetup).toHaveBeenCalledWith(
      expect.objectContaining({ timezone: Intl.DateTimeFormat().resolvedOptions().timeZone }),
    );
  });

  it("lets the user override the pre-selected timezone", async () => {
    const { wrapper } = await mountSetup();
    wrapper.findComponent(Select).vm.$emit("update:modelValue", "Europe/London");
    await completeAccountStep(wrapper);
    expect(mockedSetup).toHaveBeenCalledWith(
      expect.objectContaining({ timezone: "Europe/London" }),
    );
  });

  it("falls back to UTC if the detected timezone isn't in the known list", async () => {
    const spy = vi.spyOn(Intl, "DateTimeFormat");
    spy.mockReturnValue({
      resolvedOptions: () => ({ timeZone: "Not/A/RealZone" }),
    } as unknown as Intl.DateTimeFormat);
    try {
      const { wrapper } = await mountSetup();
      await completeAccountStep(wrapper);
      expect(mockedSetup).toHaveBeenCalledWith(expect.objectContaining({ timezone: "UTC" }));
    } finally {
      spy.mockRestore();
    }
  });

  it("surfaces API errors verbatim", async () => {
    mockedSetup.mockRejectedValue(new ApiError(409, "Setup has already been completed."));
    const { wrapper } = await mountSetup();
    await fillAccountForm(wrapper, "a-long-enough-password", "a-long-enough-password");
    expect(wrapper.find('[data-testid="setup-error"]').text()).toBe(
      "Setup has already been completed.",
    );
  });

  it("falls back to a generic failure message", async () => {
    mockedSetup.mockRejectedValue(new TypeError("fetch failed"));
    const { wrapper } = await mountSetup();
    await fillAccountForm(wrapper, "a-long-enough-password", "a-long-enough-password");
    expect(wrapper.find('[data-testid="setup-error"]').text()).toContain("Setup failed");
  });
});

describe("SetupView — storage step", () => {
  it("shows the current storage folder", async () => {
    mockedGetStorage.mockResolvedValue({
      storage_dir: "/mnt/clips",
      is_default: false,
      local_storage_quota_bytes: null,
    });
    const { wrapper } = await mountSetup();
    await completeAccountStep(wrapper);
    expect(wrapper.find('[data-testid="setup-storage-dir"]').text()).toBe("/mnt/clips");
  });

  it("shows an inline error if loading storage settings fails", async () => {
    mockedGetStorage.mockRejectedValue(new ApiError(500, "boom"));
    const { wrapper } = await mountSetup();
    await completeAccountStep(wrapper);
    expect(wrapper.find('[data-testid="setup-storage-error"]').text()).toBe("boom");
  });

  it("falls back to a generic error for a non-API storage load failure", async () => {
    mockedGetStorage.mockRejectedValue(new TypeError("down"));
    const { wrapper } = await mountSetup();
    await completeAccountStep(wrapper);
    expect(wrapper.find('[data-testid="setup-storage-error"]').text()).toBe(
      "Could not load storage settings.",
    );
  });

  it("browses, selects a folder, and saves it immediately", async () => {
    mockedBrowseStorage.mockResolvedValue({
      path: "/data/clips",
      parent_path: "/data",
      directories: [],
    });
    mockedUpdateStorage.mockResolvedValue({
      storage_dir: "/data/clips/onboarding",
      is_default: false,
      local_storage_quota_bytes: null,
    });
    const { wrapper } = await mountSetup();
    await completeAccountStep(wrapper);
    await wrapper.find('[data-testid="setup-storage-browse"]').trigger("click");
    await flushPromises();
    (document.body.querySelector('[data-testid="storage-browse-select"]') as HTMLElement).click();
    await flushPromises();
    expect(mockedUpdateStorage).toHaveBeenCalledWith({
      storage_dir: "/data/clips",
      local_storage_quota_bytes: null,
    });
    expect(wrapper.find('[data-testid="setup-storage-dir"]').text()).toBe(
      "/data/clips/onboarding",
    );
  });

  it("shows an inline error if selecting a folder fails", async () => {
    mockedBrowseStorage.mockResolvedValue({
      path: "/data/clips",
      parent_path: "/data",
      directories: [],
    });
    mockedUpdateStorage.mockRejectedValue(new ApiError(400, "not writable"));
    const { wrapper } = await mountSetup();
    await completeAccountStep(wrapper);
    await wrapper.find('[data-testid="setup-storage-browse"]').trigger("click");
    await flushPromises();
    (document.body.querySelector('[data-testid="storage-browse-select"]') as HTMLElement).click();
    await flushPromises();
    expect(wrapper.find('[data-testid="setup-storage-error"]').text()).toBe("not writable");
  });

  it("falls back to a generic error for a non-API folder save failure", async () => {
    mockedBrowseStorage.mockResolvedValue({
      path: "/data/clips",
      parent_path: "/data",
      directories: [],
    });
    mockedUpdateStorage.mockRejectedValue(new TypeError("down"));
    const { wrapper } = await mountSetup();
    await completeAccountStep(wrapper);
    await wrapper.find('[data-testid="setup-storage-browse"]').trigger("click");
    await flushPromises();
    (document.body.querySelector('[data-testid="storage-browse-select"]') as HTMLElement).click();
    await flushPromises();
    expect(wrapper.find('[data-testid="setup-storage-error"]').text()).toBe(
      "Could not update the storage folder.",
    );
  });

  it("Continue advances to the Blink step without requiring a folder change", async () => {
    const { wrapper } = await mountSetup();
    await completeAccountStep(wrapper);
    await completeStorageStep(wrapper);
    expect(wrapper.find('[data-testid="blink-step-skip"]').exists()).toBe(true);
  });
});

describe("SetupView — Blink + review steps", () => {
  it("advances to review without a linked Blink account and shows the unlinked message", async () => {
    const { wrapper } = await mountSetup();
    await completeAccountStep(wrapper);
    await completeStorageStep(wrapper);
    await wrapper.find('[data-testid="blink-step-skip"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="review-no-blink"]').exists()).toBe(true);
    expect(mockedSyncNow).not.toHaveBeenCalled();
  });

  it("shows Skip for now (not Continue) before Blink is linked, and vice versa once it is", async () => {
    const { wrapper } = await mountSetup();
    await completeAccountStep(wrapper);
    await completeStorageStep(wrapper);
    expect(wrapper.find('[data-testid="blink-step-skip"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="blink-step-continue"]').exists()).toBe(false);
  });

  it("discovers and lists cameras when Blink is already linked", async () => {
    mockedBlinkStatus.mockResolvedValue(linkedStatus());
    mockedListCameras.mockResolvedValue([
      {
        id: "cam-1",
        name: "Front Door",
        camera_type: "catalina",
        battery: null,
        enabled: true,
        last_synced_at: null,
        security_context: null,
      },
    ]);
    const { wrapper } = await mountSetup();
    await completeAccountStep(wrapper);
    await completeStorageStep(wrapper);
    await wrapper.find('[data-testid="blink-step-continue"]').trigger("click");
    await flushPromises();

    expect(mockedSyncNow).toHaveBeenCalledOnce();
    const cameraList = wrapper.find('[data-testid="review-camera-list"]');
    expect(cameraList.text()).toContain("Front Door");
    // camera_type "catalina" is translated to its real hardware name -
    // see frontend/src/lib/cameraModels.ts.
    expect(cameraList.text()).toContain("Blink Outdoor Gen 3");
  });

  it("shows Continue (not Skip) once Blink is linked", async () => {
    mockedBlinkStatus.mockResolvedValue(linkedStatus());
    const { wrapper } = await mountSetup();
    await completeAccountStep(wrapper);
    await completeStorageStep(wrapper);
    expect(wrapper.find('[data-testid="blink-step-continue"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="blink-step-skip"]').exists()).toBe(false);
  });

  it("toggles a camera's enabled state from the review step", async () => {
    mockedBlinkStatus.mockResolvedValue(linkedStatus());
    const camera = {
      id: "cam-1",
      name: "Front Door",
      camera_type: "catalina",
      battery: null,
      enabled: true,
      last_synced_at: null,
      security_context: null,
    };
    mockedListCameras.mockResolvedValue([camera]);
    mockedUpdateCamera.mockResolvedValue({ ...camera, enabled: false });
    const { wrapper } = await mountSetup();
    await completeAccountStep(wrapper);
    await completeStorageStep(wrapper);
    await wrapper.find('[data-testid="blink-step-continue"]').trigger("click");
    await flushPromises();

    await wrapper.findComponent(ToggleSwitch).vm.$emit("update:modelValue", false);
    await flushPromises();
    expect(mockedUpdateCamera).toHaveBeenCalledWith("cam-1", false, null);
  });

  it("shows a warning when sync finds no cameras at all", async () => {
    mockedBlinkStatus.mockResolvedValue(linkedStatus());
    mockedListCameras.mockResolvedValue([]);
    vi.useFakeTimers();
    try {
      const { wrapper } = await mountSetup();
      await completeAccountStep(wrapper);
      await completeStorageStep(wrapper);
      await wrapper.find('[data-testid="blink-step-continue"]').trigger("click");
      await vi.runAllTimersAsync();
      expect(wrapper.find('[data-testid="review-no-cameras"]').exists()).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });

  it("surfaces an error if camera discovery fails", async () => {
    mockedBlinkStatus.mockResolvedValue(linkedStatus());
    mockedListCameras.mockRejectedValue(new ApiError(500, "Could not reach the server."));
    const { wrapper } = await mountSetup();
    await completeAccountStep(wrapper);
    await completeStorageStep(wrapper);
    await wrapper.find('[data-testid="blink-step-continue"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="review-cameras-error"]').text()).toBe(
      "Could not reach the server.",
    );
  });

  it("falls back to a generic error for a non-API discovery failure", async () => {
    mockedBlinkStatus.mockResolvedValue(linkedStatus());
    mockedListCameras.mockRejectedValue(new TypeError("network down"));
    const { wrapper } = await mountSetup();
    await completeAccountStep(wrapper);
    await completeStorageStep(wrapper);
    await wrapper.find('[data-testid="blink-step-continue"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="review-cameras-error"]').text()).toBe(
      "Could not load cameras.",
    );
  });

  it("refresh re-runs discovery on demand", async () => {
    mockedBlinkStatus.mockResolvedValue(linkedStatus());
    mockedListCameras.mockResolvedValue([]);
    vi.useFakeTimers();
    try {
      const { wrapper } = await mountSetup();
      await completeAccountStep(wrapper);
      await completeStorageStep(wrapper);
      await wrapper.find('[data-testid="blink-step-continue"]').trigger("click");
      await vi.runAllTimersAsync();
      mockedSyncNow.mockClear();
      await wrapper.find('[data-testid="review-refresh"]').trigger("click");
      await vi.runAllTimersAsync();
      expect(mockedSyncNow).toHaveBeenCalledOnce();
    } finally {
      vi.useRealTimers();
    }
  });

  it("finishes setup and lands on the Library", async () => {
    const { wrapper, router } = await mountSetup();
    await completeAccountStep(wrapper);
    await completeStorageStep(wrapper);
    await wrapper.find('[data-testid="blink-step-skip"]').trigger("click");
    await flushPromises();
    await wrapper.find('[data-testid="finish-setup"]').trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.name).toBe("library");
  });
});
