import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import Checkbox from "primevue/checkbox";
import ToggleSwitch from "primevue/toggleswitch";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/client";
import IntegrationsView from "@/views/IntegrationsView.vue";
import { makePinia, makeRouter, mountGlobal } from "./helpers";

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  getStorageIntegrationSettings: vi.fn(),
  updateStorageIntegrationSettings: vi.fn(),
  testStorageIntegrations: vi.fn(),
}));

const toastAdd = vi.fn();
vi.mock("primevue/usetoast", () => ({
  useToast: () => ({ add: toastAdd }),
}));

import {
  getStorageIntegrationSettings,
  testStorageIntegrations,
  updateStorageIntegrationSettings,
} from "@/api";

const mockedGet = vi.mocked(getStorageIntegrationSettings);
const mockedUpdate = vi.mocked(updateStorageIntegrationSettings);
const mockedTest = vi.mocked(testStorageIntegrations);

const baseSettings = {
  s3_enabled: false,
  s3_bucket: null,
  s3_region: null,
  s3_prefix: null,
  s3_credentials_set: false,
  google_drive_enabled: false,
  google_drive_client_id: null,
  google_drive_client_secret_set: false,
  google_drive_connected: false,
  google_drive_folder_id: null,
  onedrive_enabled: false,
  onedrive_client_id: null,
  onedrive_client_secret_set: false,
  onedrive_connected: false,
  onedrive_folder_path: null,
  auto_archive_backend: "local" as const,
  auto_archive_after_days: 0,
};

beforeEach(() => {
  vi.clearAllMocks();
  mockedGet.mockResolvedValue(baseSettings);
});

async function mountView(path = "/integrations") {
  const router = makeRouter();
  await router.push(path);
  const wrapper = mount(IntegrationsView, { global: mountGlobal(makePinia(), router) });
  await flushPromises();
  return wrapper;
}

function byTestId<T>(wrapper: VueWrapper, component: new () => T, testid: string): VueWrapper<T> {
  return wrapper
    .findAllComponents(component as never)
    .find((c) => c.attributes("data-testid") === testid) as unknown as VueWrapper<T>;
}

describe("IntegrationsView loading", () => {
  it("shows a skeleton while loading", async () => {
    mockedGet.mockReturnValue(new Promise(() => {}));
    const router = makeRouter();
    await router.push("/integrations");
    const wrapper = mount(IntegrationsView, { global: mountGlobal(makePinia(), router) });
    expect(wrapper.find('[data-testid="integrations-loading"]').exists()).toBe(true);
  });

  it("shows a load error on failure", async () => {
    mockedGet.mockRejectedValue(new ApiError(500, "boom"));
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="integrations-load-error"]').text()).toBe("boom");
  });

  it("falls back to a generic load error for non-API failures", async () => {
    mockedGet.mockRejectedValue(new TypeError("down"));
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="integrations-load-error"]').text()).toBe(
      "Could not load integrations.",
    );
  });
});

describe("IntegrationsView cards", () => {
  it("lists all three integrations by default", async () => {
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="integration-card-s3"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="integration-card-google_drive"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="integration-card-onedrive"]').exists()).toBe(true);
  });

  it("colors the S3 icon (pi-amazon carries no brand color of its own)", async () => {
    const wrapper = await mountView();
    const icon = wrapper.find('[data-testid="integration-card-s3"] .pi-amazon');
    expect(icon.attributes("style")).toContain("color: #ff9900");
  });

  it("shows Not connected for a disabled integration", async () => {
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="integration-status-s3"]').text()).toBe("Not connected");
  });

  it("shows Needs attention for an enabled-but-unconfigured integration", async () => {
    mockedGet.mockResolvedValue({ ...baseSettings, s3_enabled: true });
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="integration-status-s3"]').text()).toBe("Needs attention");
  });

  it("shows Connected once fully configured", async () => {
    mockedGet.mockResolvedValue({ ...baseSettings, s3_enabled: true, s3_credentials_set: true });
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="integration-status-s3"]').text()).toBe("Connected");
  });

  it("shows Connected for Google Drive once enabled and its OAuth flow has completed", async () => {
    mockedGet.mockResolvedValue({
      ...baseSettings,
      google_drive_enabled: true,
      google_drive_connected: true,
    });
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="integration-status-google_drive"]').text()).toBe(
      "Connected",
    );
  });
});

describe("IntegrationsView search and filter", () => {
  it("filters by search text", async () => {
    const wrapper = await mountView();
    await wrapper.find('[data-testid="integrations-search"]').setValue("drive");
    expect(wrapper.find('[data-testid="integration-card-s3"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="integration-card-google_drive"]').exists()).toBe(true);
  });

  it("shows an empty state when nothing matches", async () => {
    const wrapper = await mountView();
    await wrapper.find('[data-testid="integrations-search"]').setValue("nonexistent");
    expect(wrapper.text()).toContain("No integrations match");
  });

  it("filters by category", async () => {
    const wrapper = await mountView();
    const filter = wrapper.findComponent({ name: "SelectButton" });
    await filter.vm.$emit("update:modelValue", "Storage");
    await flushPromises();
    expect(wrapper.find('[data-testid="integration-card-s3"]').exists()).toBe(true);
  });
});

describe("IntegrationsView configure forms", () => {
  it("toggles the S3 form open and closed", async () => {
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="integration-form-s3"]').exists()).toBe(false);
    await wrapper.find('[data-testid="integration-configure-s3"]').trigger("click");
    expect(wrapper.find('[data-testid="integration-form-s3"]').exists()).toBe(true);
    await wrapper.find('[data-testid="integration-configure-s3"]').trigger("click");
    expect(wrapper.find('[data-testid="integration-form-s3"]').exists()).toBe(false);
  });

  it("only one provider's form is expanded at a time", async () => {
    const wrapper = await mountView();
    await wrapper.find('[data-testid="integration-configure-s3"]').trigger("click");
    await wrapper.find('[data-testid="integration-configure-google_drive"]').trigger("click");
    expect(wrapper.find('[data-testid="integration-form-s3"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="integration-form-google_drive"]').exists()).toBe(true);
  });

  it("saves S3 settings and preserves other providers' fields", async () => {
    mockedGet.mockResolvedValue({
      ...baseSettings,
      google_drive_enabled: true,
      google_drive_client_id: "existing-drive-client",
      auto_archive_backend: "google_drive",
      auto_archive_after_days: 5,
    });
    mockedUpdate.mockResolvedValue({ ...baseSettings, s3_enabled: true, s3_bucket: "my-bucket" });
    const wrapper = await mountView();
    await wrapper.find('[data-testid="integration-configure-s3"]').trigger("click");
    await byTestId(wrapper, ToggleSwitch, "s3-enabled").vm.$emit("update:modelValue", true);
    await wrapper.find('[data-testid="s3-bucket"]').setValue("my-bucket");
    await wrapper.find('[data-testid="s3-region"]').setValue("us-east-1");
    await wrapper.find('[data-testid="s3-access-key"] input').setValue("AKIA123");
    await wrapper.find('[data-testid="s3-secret-key"] input').setValue("shh-its-a-secret");
    await wrapper.find('[data-testid="integration-form-s3"]').trigger("submit.prevent");
    await flushPromises();
    expect(mockedUpdate).toHaveBeenCalledWith(
      expect.objectContaining({
        s3_enabled: true,
        s3_bucket: "my-bucket",
        s3_region: "us-east-1",
        s3_prefix: null,
        s3_access_key_id: "AKIA123",
        s3_secret_access_key: "shh-its-a-secret",
        google_drive_enabled: true,
        google_drive_client_id: "existing-drive-client",
        auto_archive_backend: "google_drive",
        auto_archive_after_days: 5,
      }),
    );
    expect(toastAdd).toHaveBeenCalledWith(expect.objectContaining({ severity: "success" }));
  });

  it("clears saved S3 credentials when requested", async () => {
    mockedGet.mockResolvedValue({
      ...baseSettings,
      s3_enabled: true,
      s3_bucket: "my-bucket",
      s3_credentials_set: true,
    });
    mockedUpdate.mockResolvedValue(baseSettings);
    const wrapper = await mountView();
    await wrapper.find('[data-testid="integration-configure-s3"]').trigger("click");
    await byTestId(wrapper, Checkbox, "s3-clear-credentials").vm.$emit("update:modelValue", true);
    await wrapper.find('[data-testid="integration-form-s3"]').trigger("submit.prevent");
    await flushPromises();
    expect(mockedUpdate).toHaveBeenCalledWith(
      expect.objectContaining({ s3_access_key_id: "", s3_secret_access_key: "" }),
    );
  });

  it("shows an inline error when saving fails", async () => {
    mockedUpdate.mockRejectedValue(new ApiError(400, "nope"));
    const wrapper = await mountView();
    await wrapper.find('[data-testid="integration-configure-s3"]').trigger("click");
    await wrapper.find('[data-testid="integration-form-s3"]').trigger("submit.prevent");
    await flushPromises();
    expect(wrapper.text()).toContain("nope");
  });

  it("falls back to a generic inline error for non-API save failures", async () => {
    mockedUpdate.mockRejectedValue(new TypeError("down"));
    const wrapper = await mountView();
    await wrapper.find('[data-testid="integration-configure-s3"]').trigger("click");
    await wrapper.find('[data-testid="integration-form-s3"]').trigger("submit.prevent");
    await flushPromises();
    expect(wrapper.text()).toContain("Unexpected error.");
  });

  it("disables the Google Drive connect button until credentials are saved", async () => {
    const wrapper = await mountView();
    await wrapper.find('[data-testid="integration-configure-google_drive"]').trigger("click");
    const connect = wrapper.find('[data-testid="drive-connect"]');
    expect(connect.attributes("disabled")).toBeDefined();
  });

  it("enables the Google Drive connect button once a client id/secret are saved", async () => {
    mockedGet.mockResolvedValue({
      ...baseSettings,
      google_drive_client_id: "client-1",
      google_drive_client_secret_set: true,
    });
    const wrapper = await mountView();
    await wrapper.find('[data-testid="integration-configure-google_drive"]').trigger("click");
    const connect = wrapper.find('[data-testid="drive-connect"]');
    expect(connect.attributes("disabled")).toBeUndefined();
  });

  it("navigates the browser to the OAuth start URL when Connect is clicked", async () => {
    mockedGet.mockResolvedValue({
      ...baseSettings,
      google_drive_client_id: "client-1",
      google_drive_client_secret_set: true,
    });
    const originalLocation = window.location;
    const assignedHref = vi.fn();
    Object.defineProperty(window, "location", {
      value: { get href() { return ""; }, set href(v: string) { assignedHref(v); } },
      writable: true,
    });
    const wrapper = await mountView();
    await wrapper.find('[data-testid="integration-configure-google_drive"]').trigger("click");
    await wrapper.find('[data-testid="drive-connect"]').trigger("click");
    expect(assignedHref).toHaveBeenCalledWith(
      "/api/settings/storage-integrations/google-drive/oauth/start",
    );
    Object.defineProperty(window, "location", { value: originalLocation, writable: true });
  });

  it("saves Google Drive settings", async () => {
    mockedUpdate.mockResolvedValue(baseSettings);
    const wrapper = await mountView();
    await wrapper.find('[data-testid="integration-configure-google_drive"]').trigger("click");
    await byTestId(wrapper, ToggleSwitch, "drive-enabled").vm.$emit("update:modelValue", true);
    await wrapper.find('[data-testid="drive-client-id"]').setValue("gd-client");
    await wrapper.find('[data-testid="drive-client-secret"] input').setValue("gd-secret");
    await wrapper.find('[data-testid="integration-form-google_drive"]').trigger("submit.prevent");
    await flushPromises();
    expect(mockedUpdate).toHaveBeenCalledWith(
      expect.objectContaining({
        google_drive_enabled: true,
        google_drive_client_id: "gd-client",
        google_drive_client_secret: "gd-secret",
      }),
    );
  });

  it("saves a blank Google Drive client id as null", async () => {
    mockedGet.mockResolvedValue({ ...baseSettings, google_drive_client_id: "gd-client" });
    mockedUpdate.mockResolvedValue(baseSettings);
    const wrapper = await mountView();
    await wrapper.find('[data-testid="integration-configure-google_drive"]').trigger("click");
    await wrapper.find('[data-testid="drive-client-id"]').setValue("");
    await wrapper.find('[data-testid="integration-form-google_drive"]').trigger("submit.prevent");
    await flushPromises();
    expect(mockedUpdate).toHaveBeenCalledWith(
      expect.objectContaining({ google_drive_client_id: null }),
    );
  });

  it("saves OneDrive settings", async () => {
    mockedUpdate.mockResolvedValue(baseSettings);
    const wrapper = await mountView();
    await wrapper.find('[data-testid="integration-configure-onedrive"]').trigger("click");
    await byTestId(wrapper, ToggleSwitch, "onedrive-enabled").vm.$emit("update:modelValue", true);
    await wrapper.find('[data-testid="onedrive-client-id"]').setValue("od-client");
    await wrapper.find('[data-testid="onedrive-client-secret"] input').setValue("od-secret");
    await wrapper.find('[data-testid="integration-form-onedrive"]').trigger("submit.prevent");
    await flushPromises();
    expect(mockedUpdate).toHaveBeenCalledWith(
      expect.objectContaining({
        onedrive_enabled: true,
        onedrive_client_id: "od-client",
        onedrive_client_secret: "od-secret",
        onedrive_folder_path: null,
      }),
    );
  });

  it("saves a blank OneDrive client id as null", async () => {
    mockedGet.mockResolvedValue({ ...baseSettings, onedrive_client_id: "od-client" });
    mockedUpdate.mockResolvedValue(baseSettings);
    const wrapper = await mountView();
    await wrapper.find('[data-testid="integration-configure-onedrive"]').trigger("click");
    await wrapper.find('[data-testid="onedrive-client-id"]').setValue("");
    await wrapper.find('[data-testid="integration-form-onedrive"]').trigger("submit.prevent");
    await flushPromises();
    expect(mockedUpdate).toHaveBeenCalledWith(
      expect.objectContaining({ onedrive_client_id: null }),
    );
  });

  it("disables the OneDrive connect button until credentials are saved", async () => {
    const wrapper = await mountView();
    await wrapper.find('[data-testid="integration-configure-onedrive"]').trigger("click");
    expect(wrapper.find('[data-testid="onedrive-connect"]').attributes("disabled")).toBeDefined();
  });

  it("navigates the browser to the OneDrive OAuth start URL when Connect is clicked", async () => {
    mockedGet.mockResolvedValue({
      ...baseSettings,
      onedrive_client_id: "od-client",
      onedrive_client_secret_set: true,
    });
    const originalLocation = window.location;
    const assignedHref = vi.fn();
    Object.defineProperty(window, "location", {
      value: {
        get href() {
          return "";
        },
        set href(v: string) {
          assignedHref(v);
        },
      },
      writable: true,
    });
    const wrapper = await mountView();
    await wrapper.find('[data-testid="integration-configure-onedrive"]').trigger("click");
    await wrapper.find('[data-testid="onedrive-connect"]').trigger("click");
    expect(assignedHref).toHaveBeenCalledWith(
      "/api/settings/storage-integrations/onedrive/oauth/start",
    );
    Object.defineProperty(window, "location", { value: originalLocation, writable: true });
  });

  it("clears a saved OneDrive client secret when requested", async () => {
    mockedGet.mockResolvedValue({
      ...baseSettings,
      onedrive_enabled: true,
      onedrive_client_id: "od-client",
      onedrive_client_secret_set: true,
    });
    mockedUpdate.mockResolvedValue(baseSettings);
    const wrapper = await mountView();
    await wrapper.find('[data-testid="integration-configure-onedrive"]').trigger("click");
    await byTestId(wrapper, Checkbox, "onedrive-clear-secret").vm.$emit("update:modelValue", true);
    await wrapper.find('[data-testid="integration-form-onedrive"]').trigger("submit.prevent");
    await flushPromises();
    expect(mockedUpdate).toHaveBeenCalledWith(
      expect.objectContaining({ onedrive_client_secret: "" }),
    );
  });

  it("clears a saved Google Drive client secret when requested", async () => {
    mockedGet.mockResolvedValue({
      ...baseSettings,
      google_drive_enabled: true,
      google_drive_client_id: "gd-client",
      google_drive_client_secret_set: true,
    });
    mockedUpdate.mockResolvedValue(baseSettings);
    const wrapper = await mountView();
    await wrapper.find('[data-testid="integration-configure-google_drive"]').trigger("click");
    await byTestId(wrapper, Checkbox, "drive-clear-secret").vm.$emit("update:modelValue", true);
    await wrapper.find('[data-testid="integration-form-google_drive"]').trigger("submit.prevent");
    await flushPromises();
    expect(mockedUpdate).toHaveBeenCalledWith(
      expect.objectContaining({
        google_drive_client_secret: "",
        google_drive_folder_id: null,
      }),
    );
  });

  it("shows a hint pointing to the Storage tab for folder selection", async () => {
    const wrapper = await mountView();
    await wrapper.find('[data-testid="integration-configure-s3"]').trigger("click");
    expect(wrapper.find('[data-testid="integration-form-s3"]').text()).toContain("Storage tab");
  });

  it("tests the connection from within an expanded form", async () => {
    mockedTest.mockResolvedValue({
      s3: { ok: true, detail: "Connected." },
      google_drive: null,
      onedrive: null,
    });
    const wrapper = await mountView();
    await wrapper.find('[data-testid="integration-configure-s3"]').trigger("click");
    await wrapper.find('[data-testid="integration-test-s3"]').trigger("click");
    await flushPromises();
    expect(mockedTest).toHaveBeenCalled();
    expect(wrapper.find('[data-testid="integration-test-result-s3"]').text()).toContain(
      "Connected.",
    );
  });
});

describe("IntegrationsView test connections", () => {
  it("runs the test and shows per-provider results", async () => {
    mockedTest.mockResolvedValue({
      s3: { ok: true, detail: "Connected." },
      google_drive: { ok: false, detail: "invalid_grant" },
      onedrive: null,
    });
    const wrapper = await mountView();
    await wrapper.find('[data-testid="test-all-integrations"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="integration-test-result-s3"]').text()).toContain(
      "Connected.",
    );
    expect(wrapper.find('[data-testid="integration-test-result-google_drive"]').text()).toContain(
      "invalid_grant",
    );
    expect(wrapper.find('[data-testid="integration-test-result-onedrive"]').exists()).toBe(false);
  });

  it("treats an absent S3/Google Drive result the same as untested", async () => {
    mockedTest.mockResolvedValue({
      s3: null,
      google_drive: null,
      onedrive: { ok: true, detail: "Connected." },
    });
    const wrapper = await mountView();
    await wrapper.find('[data-testid="test-all-integrations"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="integration-test-result-s3"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="integration-test-result-google_drive"]').exists()).toBe(
      false,
    );
    expect(wrapper.find('[data-testid="integration-test-result-onedrive"]').text()).toContain(
      "Connected.",
    );
  });

  it("shows a Not configured indicator for an enabled provider that tested null", async () => {
    mockedGet.mockResolvedValue({ ...baseSettings, s3_enabled: true });
    mockedTest.mockResolvedValue({ s3: null, google_drive: null, onedrive: null });
    const wrapper = await mountView();
    await wrapper.find('[data-testid="test-all-integrations"]').trigger("click");
    await flushPromises();

    expect(wrapper.find('[data-testid="integration-test-result-s3"]').text()).toContain(
      "Not configured",
    );
    // Still disabled - stays silent, same as before this fix.
    expect(wrapper.find('[data-testid="integration-test-result-google_drive"]').exists()).toBe(
      false,
    );
  });

  it("does not show Not configured before a test has actually been run", async () => {
    mockedGet.mockResolvedValue({ ...baseSettings, s3_enabled: true });
    const wrapper = await mountView();
    expect(wrapper.find('[data-testid="integration-test-result-s3"]').exists()).toBe(false);
  });

  it("toasts an error if the test request itself fails", async () => {
    mockedTest.mockRejectedValue(new ApiError(500, "down"));
    const wrapper = await mountView();
    await wrapper.find('[data-testid="test-all-integrations"]').trigger("click");
    await flushPromises();
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "error", detail: "down" }),
    );
  });

  it("toasts a generic error for a non-API test failure", async () => {
    mockedTest.mockRejectedValue(new TypeError("down"));
    const wrapper = await mountView();
    await wrapper.find('[data-testid="test-all-integrations"]').trigger("click");
    await flushPromises();
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "error", detail: "Unexpected error." }),
    );
  });
});

function openDialog(dialogs: ReturnType<typeof findDialogs>) {
  return dialogs.find((d) => d.props("visible"));
}

function findDialogs(wrapper: { findAllComponents: (sel: { name: string }) => unknown[] }) {
  return wrapper.findAllComponents({ name: "Dialog" }) as {
    props: (name: string) => unknown;
    vm: { $emit: (event: string, value: unknown) => void };
  }[];
}

describe("IntegrationsView help dialogs", () => {
  it("opens and closes the S3 help dialog", async () => {
    const wrapper = await mountView();
    await wrapper.find('[data-testid="integration-help-s3"]').trigger("click");
    await flushPromises();
    expect(document.body.textContent).toContain("Connecting Amazon S3");
    openDialog(findDialogs(wrapper))!.vm.$emit("update:visible", false);
    await flushPromises();
  });

  it("opens and closes the Google Drive help dialog with the redirect URI", async () => {
    const wrapper = await mountView();
    await wrapper.find('[data-testid="integration-help-google_drive"]').trigger("click");
    await flushPromises();
    expect(document.body.textContent).toContain(
      "/api/settings/storage-integrations/google-drive/oauth/callback",
    );
    openDialog(findDialogs(wrapper))!.vm.$emit("update:visible", false);
    await flushPromises();
  });

  it("opens and closes the OneDrive help dialog with the redirect URI", async () => {
    const wrapper = await mountView();
    await wrapper.find('[data-testid="integration-help-onedrive"]').trigger("click");
    await flushPromises();
    expect(document.body.textContent).toContain(
      "/api/settings/storage-integrations/onedrive/oauth/callback",
    );
    openDialog(findDialogs(wrapper))!.vm.$emit("update:visible", false);
    await flushPromises();
  });
});

describe("IntegrationsView OAuth redirect toasts", () => {
  it("toasts success when redirected back with ?connected=", async () => {
    await mountView("/integrations?connected=google_drive");
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "success", summary: "Google Drive connected" }),
    );
  });

  it("toasts an error when redirected back with ?error=", async () => {
    await mountView("/integrations?error=onedrive");
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "error", summary: "Could not connect Microsoft OneDrive" }),
    );
  });

  it("falls back to the raw key when redirected back for an unknown provider", async () => {
    await mountView("/integrations?connected=dropbox&error=box");
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "success", summary: "dropbox connected" }),
    );
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "error", summary: "Could not connect box" }),
    );
  });
});
