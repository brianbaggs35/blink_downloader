import { flushPromises, mount } from "@vue/test-utils";
import InputNumber from "primevue/inputnumber";
import Select from "primevue/select";
import ToggleSwitch from "primevue/toggleswitch";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/client";
import SettingsBiometricsPanel from "@/components/SettingsBiometricsPanel.vue";
import { makePinia, mountGlobal } from "./helpers";

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  getBiometricsSettings: vi.fn(),
  updateBiometricsSettings: vi.fn(),
  verifyBiometricsModel: vi.fn(),
}));

const toastAdd = vi.fn();
vi.mock("primevue/usetoast", () => ({
  useToast: () => ({ add: toastAdd }),
}));

import { getBiometricsSettings, updateBiometricsSettings, verifyBiometricsModel } from "@/api";

const mockedGet = vi.mocked(getBiometricsSettings);
const mockedUpdate = vi.mocked(updateBiometricsSettings);
const mockedVerify = vi.mocked(verifyBiometricsModel);

const baseSettings = {
  enabled: true,
  model_pack: "buffalo_l" as const,
  execution_provider_preference: "auto" as const,
  recognition_threshold: 0.4,
  available_providers: ["CPUExecutionProvider"],
  updated_at: "2026-07-25T00:00:00Z",
};

beforeEach(() => {
  vi.clearAllMocks();
});

function mountPanel() {
  return mount(SettingsBiometricsPanel, { global: mountGlobal(makePinia()) });
}

describe("SettingsBiometricsPanel loading", () => {
  it("shows a loading skeleton while fetching", () => {
    mockedGet.mockReturnValue(new Promise(() => {}));
    const wrapper = mountPanel();
    expect(wrapper.find('[data-testid="biometrics-settings-loading"]').exists()).toBe(true);
  });

  it("shows the API error message when loading fails", async () => {
    mockedGet.mockRejectedValue(new ApiError(500, "Server exploded"));
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find('[data-testid="biometrics-settings-load-error"]').text()).toBe(
      "Server exploded",
    );
  });

  it("falls back to a generic load error for non-API failures", async () => {
    mockedGet.mockRejectedValue(new TypeError("down"));
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find('[data-testid="biometrics-settings-load-error"]').text()).toBe(
      "Could not load biometrics settings.",
    );
  });

  it("populates fields from the loaded settings", async () => {
    mockedGet.mockResolvedValue(baseSettings);
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find('[data-testid="biometrics-detected-providers"]').text()).toBe("CPU only");
  });

  it("shows a GPU tag when a non-CPU provider is detected", async () => {
    mockedGet.mockResolvedValue({
      ...baseSettings,
      available_providers: ["CUDAExecutionProvider", "CPUExecutionProvider"],
    });
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find('[data-testid="biometrics-detected-providers"]').text()).toBe(
      "GPU available",
    );
  });
});

describe("SettingsBiometricsPanel save", () => {
  beforeEach(() => {
    mockedGet.mockResolvedValue(baseSettings);
  });

  it("saves the current field values", async () => {
    mockedUpdate.mockResolvedValue(baseSettings);
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="biometrics-settings-form"]').trigger("submit.prevent");
    await flushPromises();
    expect(mockedUpdate).toHaveBeenCalledWith({
      enabled: true,
      model_pack: "buffalo_l",
      execution_provider_preference: "auto",
      recognition_threshold: 0.4,
    });
    expect(toastAdd).toHaveBeenCalledWith(expect.objectContaining({ severity: "success" }));
  });

  it("toggles enabled and changes model pack / provider preference / threshold", async () => {
    mockedUpdate.mockResolvedValue({
      ...baseSettings,
      enabled: false,
      model_pack: "buffalo_sc",
      execution_provider_preference: "cpu",
      recognition_threshold: 0.6,
    });
    const wrapper = mountPanel();
    await flushPromises();

    const toggles = wrapper.findAllComponents(ToggleSwitch);
    await toggles[0]!.vm.$emit("update:modelValue", false);

    const selects = wrapper.findAllComponents(Select);
    await selects[0]!.vm.$emit("update:modelValue", "buffalo_sc");
    await selects[1]!.vm.$emit("update:modelValue", "cpu");

    const numbers = wrapper.findAllComponents(InputNumber);
    await numbers[0]!.vm.$emit("update:modelValue", 0.6);
    await flushPromises();

    await wrapper.find('[data-testid="biometrics-settings-form"]').trigger("submit.prevent");
    await flushPromises();

    expect(mockedUpdate).toHaveBeenCalledWith({
      enabled: false,
      model_pack: "buffalo_sc",
      execution_provider_preference: "cpu",
      recognition_threshold: 0.6,
    });
  });

  it("shows the API error message when saving fails", async () => {
    mockedUpdate.mockRejectedValue(new ApiError(400, "Bad threshold."));
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="biometrics-settings-form"]').trigger("submit.prevent");
    await flushPromises();
    expect(wrapper.find('[data-testid="biometrics-settings-save-error"]').text()).toBe(
      "Bad threshold.",
    );
  });

  it("falls back to a generic save error for non-API failures", async () => {
    mockedUpdate.mockRejectedValue(new TypeError("down"));
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="biometrics-settings-form"]').trigger("submit.prevent");
    await flushPromises();
    expect(wrapper.find('[data-testid="biometrics-settings-save-error"]').text()).toBe(
      "Unexpected error.",
    );
  });
});

describe("SettingsBiometricsPanel verify model", () => {
  beforeEach(() => {
    mockedGet.mockResolvedValue(baseSettings);
  });

  it("shows the resolved providers on success", async () => {
    mockedVerify.mockResolvedValue({ model_pack: "buffalo_l", providers: ["CPUExecutionProvider"] });
    const wrapper = mountPanel();
    await flushPromises();

    await wrapper.find('[data-testid="verify-model"]').trigger("click");
    await flushPromises();

    expect(mockedVerify).toHaveBeenCalled();
    expect(wrapper.find('[data-testid="verify-model-success"]').text()).toContain(
      "CPUExecutionProvider",
    );
    expect(toastAdd).toHaveBeenCalledWith(expect.objectContaining({ severity: "success" }));
  });

  it("shows the API error message when verification fails", async () => {
    mockedVerify.mockRejectedValue(new ApiError(502, "Could not download the model."));
    const wrapper = mountPanel();
    await flushPromises();

    await wrapper.find('[data-testid="verify-model"]').trigger("click");
    await flushPromises();

    expect(wrapper.find('[data-testid="verify-model-error"]').text()).toBe(
      "Could not download the model.",
    );
  });

  it("falls back to a generic error for non-API verify failures", async () => {
    mockedVerify.mockRejectedValue(new TypeError("network down"));
    const wrapper = mountPanel();
    await flushPromises();

    await wrapper.find('[data-testid="verify-model"]').trigger("click");
    await flushPromises();

    expect(wrapper.find('[data-testid="verify-model-error"]').text()).toBe(
      "Could not verify the model. Check your connection and try again.",
    );
  });

  it("disables the verify button while biometrics is off", async () => {
    mockedGet.mockResolvedValue({ ...baseSettings, enabled: false });
    const wrapper = mountPanel();
    await flushPromises();

    const button = wrapper.find('[data-testid="verify-model"]');
    expect(button.attributes("disabled")).toBeDefined();
  });
});
