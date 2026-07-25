import { flushPromises, mount } from "@vue/test-utils";
import InputNumber from "primevue/inputnumber";
import Select from "primevue/select";
import ToggleSwitch from "primevue/toggleswitch";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/client";
import SettingsAiProviderPanel from "@/components/SettingsAiProviderPanel.vue";
import { makePinia, mountGlobal } from "./helpers";

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  getAiSettings: vi.fn(),
  updateAiSettings: vi.fn(),
  testAiConnection: vi.fn(),
}));

const toastAdd = vi.fn();
vi.mock("primevue/usetoast", () => ({
  useToast: () => ({ add: toastAdd }),
}));

import { getAiSettings, testAiConnection, updateAiSettings } from "@/api";

const mockedGet = vi.mocked(getAiSettings);
const mockedUpdate = vi.mocked(updateAiSettings);
const mockedTest = vi.mocked(testAiConnection);

const baseSettings = {
  enabled: true,
  tier1_provider: "openai" as const,
  tier1_model: "gpt-4o-mini",
  tier1_api_key_set: true,
  tier1_base_url: null,
  tier2_enabled: true,
  tier2_provider: "anthropic" as const,
  tier2_model: "claude-haiku-4-5",
  tier2_api_key_set: false,
  tier2_base_url: "https://custom.example.com",
  keyframes_per_clip: 4,
  tier2_suspicion_threshold: 0.5,
  feedback_context_count: 5,
};

const emptySettings = {
  enabled: false,
  tier1_provider: null,
  tier1_model: null,
  tier1_api_key_set: false,
  tier1_base_url: null,
  tier2_enabled: true,
  tier2_provider: null,
  tier2_model: null,
  tier2_api_key_set: false,
  tier2_base_url: null,
  keyframes_per_clip: 4,
  tier2_suspicion_threshold: 0.5,
  feedback_context_count: 5,
};

beforeEach(() => {
  vi.clearAllMocks();
});

function mountPanel() {
  return mount(SettingsAiProviderPanel, { global: mountGlobal(makePinia()) });
}

describe("SettingsAiProviderPanel loading", () => {
  it("shows a loading skeleton while fetching", () => {
    mockedGet.mockReturnValue(new Promise(() => {}));
    const wrapper = mountPanel();
    expect(wrapper.find('[data-testid="ai-provider-loading"]').exists()).toBe(true);
  });

  it("shows the API error message when loading fails", async () => {
    mockedGet.mockRejectedValue(new ApiError(500, "Server exploded"));
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find('[data-testid="ai-provider-load-error"]').text()).toBe("Server exploded");
  });

  it("falls back to a generic load error for non-API failures", async () => {
    mockedGet.mockRejectedValue(new TypeError("down"));
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find('[data-testid="ai-provider-load-error"]').text()).toBe(
      "Could not load AI settings.",
    );
  });

  it("populates fields from the loaded settings, including a set-key placeholder", async () => {
    mockedGet.mockResolvedValue(baseSettings);
    const wrapper = mountPanel();
    await flushPromises();
    const modelInput = wrapper.find('[data-testid="tier1-model"]').element as HTMLInputElement;
    expect(modelInput.value).toBe("gpt-4o-mini");
    const keyInput = wrapper.find('[data-testid="tier1-api-key"] input')
      .element as HTMLInputElement;
    expect(keyInput.placeholder).toContain("saved");
  });

  it("renders blank/default fields when nothing is configured yet", async () => {
    mockedGet.mockResolvedValue(emptySettings);
    const wrapper = mountPanel();
    await flushPromises();
    const keyInput = wrapper.find('[data-testid="tier1-api-key"] input')
      .element as HTMLInputElement;
    expect(keyInput.placeholder).toBe("Not set");
  });
});

describe("SettingsAiProviderPanel save", () => {
  beforeEach(() => {
    mockedGet.mockResolvedValue(baseSettings);
  });

  it("saves with unchanged keys (null) when nothing new was typed", async () => {
    mockedUpdate.mockResolvedValue(baseSettings);
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="ai-provider-form"]').trigger("submit.prevent");
    await flushPromises();
    expect(mockedUpdate).toHaveBeenCalledWith(
      expect.objectContaining({ tier1_api_key: null, tier2_api_key: null }),
    );
    expect(toastAdd).toHaveBeenCalledWith(expect.objectContaining({ severity: "success" }));
  });

  it("sends a typed replacement key and clears the input afterwards", async () => {
    mockedUpdate.mockResolvedValue({ ...baseSettings, tier1_api_key_set: true });
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="tier1-api-key"] input').setValue("sk-new-key");
    await wrapper.find('[data-testid="ai-provider-form"]').trigger("submit.prevent");
    await flushPromises();
    expect(mockedUpdate).toHaveBeenCalledWith(
      expect.objectContaining({ tier1_api_key: "sk-new-key" }),
    );
    const keyInput = wrapper.find('[data-testid="tier1-api-key"] input')
      .element as HTMLInputElement;
    expect(keyInput.value).toBe("");
  });

  it("clears a saved key when its checkbox is checked without typing a new one", async () => {
    mockedUpdate.mockResolvedValue({ ...baseSettings, tier1_api_key_set: false });
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="tier1-clear-key"]').setValue(true);
    await wrapper.find('[data-testid="ai-provider-form"]').trigger("submit.prevent");
    await flushPromises();
    expect(mockedUpdate).toHaveBeenCalledWith(expect.objectContaining({ tier1_api_key: "" }));
  });

  it("omits tier2 fields' visibility when tier2 is disabled, still saving tier2_enabled false", async () => {
    mockedUpdate.mockResolvedValue({ ...baseSettings, tier2_enabled: false });
    const wrapper = mountPanel();
    await flushPromises();
    const toggles = wrapper.findAllComponents(ToggleSwitch);
    await toggles[1]!.vm.$emit("update:modelValue", false);
    await flushPromises();
    expect(wrapper.find('[data-testid="tier2-provider"]').exists()).toBe(false);
    await wrapper.find('[data-testid="ai-provider-form"]').trigger("submit.prevent");
    await flushPromises();
    expect(mockedUpdate).toHaveBeenCalledWith(expect.objectContaining({ tier2_enabled: false }));
  });

  it("shows the API error message when saving fails", async () => {
    mockedUpdate.mockRejectedValue(new ApiError(400, "Bad model name."));
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="ai-provider-form"]').trigger("submit.prevent");
    await flushPromises();
    expect(wrapper.find('[data-testid="ai-provider-save-error"]').text()).toBe("Bad model name.");
  });

  it("falls back to a generic save error for non-API failures", async () => {
    mockedUpdate.mockRejectedValue(new TypeError("down"));
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="ai-provider-form"]').trigger("submit.prevent");
    await flushPromises();
    expect(wrapper.find('[data-testid="ai-provider-save-error"]').text()).toBe(
      "Unexpected error.",
    );
  });

  it("toggles master AI enabled and sends the update", async () => {
    mockedUpdate.mockResolvedValue(baseSettings);
    const wrapper = mountPanel();
    await flushPromises();
    const toggles = wrapper.findAllComponents(ToggleSwitch);
    await toggles[0]!.vm.$emit("update:modelValue", false);
    await wrapper.find('[data-testid="ai-provider-form"]').trigger("submit.prevent");
    await flushPromises();
    expect(mockedUpdate).toHaveBeenCalledWith(expect.objectContaining({ enabled: false }));
  });

  it("changes provider via the select and reflects the new model placeholder", async () => {
    mockedGet.mockResolvedValue(emptySettings);
    const wrapper = mountPanel();
    await flushPromises();
    const selects = wrapper.findAllComponents(Select);
    await selects[0]!.vm.$emit("update:modelValue", "ollama");
    await flushPromises();
    const modelInput = wrapper.find('[data-testid="tier1-model"]').element as HTMLInputElement;
    expect(modelInput.placeholder).toBe("llava");
    const baseUrlInput = wrapper.find('[data-testid="tier1-base-url"]')
      .element as HTMLInputElement;
    expect(baseUrlInput.placeholder).toBe("http://localhost:11434");
  });
});

describe("SettingsAiProviderPanel test connection", () => {
  beforeEach(() => {
    mockedGet.mockResolvedValue(baseSettings);
  });

  it("requires a provider and model before testing", async () => {
    mockedGet.mockResolvedValue(emptySettings);
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="tier1-test"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="tier1-test-result"]').text()).toContain(
      "Choose a provider and model first.",
    );
    expect(mockedTest).not.toHaveBeenCalled();
  });

  it("reports success with the returned detail", async () => {
    mockedTest.mockResolvedValue({ ok: true, detail: "All good." });
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="tier1-test"]').trigger("click");
    await flushPromises();
    expect(mockedTest).toHaveBeenCalledWith({
      tier: "tier1",
      provider: "openai",
      model: "gpt-4o-mini",
      api_key: null,
      base_url: null,
    });
    const result = wrapper.find('[data-testid="tier1-test-result"]');
    expect(result.text()).toContain("All good.");
    expect(result.classes()).toContain("ok");
  });

  it("falls back to a default success message when detail is missing", async () => {
    mockedTest.mockResolvedValue({ ok: true, detail: null });
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="tier1-test"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="tier1-test-result"]').text()).toContain("Connected.");
  });

  it("reports failure with the returned detail, styled as failing", async () => {
    mockedTest.mockResolvedValue({ ok: false, detail: "Invalid API key." });
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="tier2-test"]').trigger("click");
    await flushPromises();
    const result = wrapper.find('[data-testid="tier2-test-result"]');
    expect(result.text()).toContain("Invalid API key.");
    expect(result.classes()).toContain("fail");
  });

  it("falls back to a default failure message when detail is missing", async () => {
    mockedTest.mockResolvedValue({ ok: false, detail: null });
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="tier1-test"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="tier1-test-result"]').text()).toContain("Failed.");
  });

  it("shows the API error message when the test call itself throws", async () => {
    mockedTest.mockRejectedValue(new ApiError(401, "Unauthorized."));
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="tier1-test"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="tier1-test-result"]').text()).toContain("Unauthorized.");
  });

  it("falls back to a generic error when the test call throws a non-API error", async () => {
    mockedTest.mockRejectedValue(new TypeError("down"));
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="tier1-test"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="tier1-test-result"]').text()).toContain(
      "Unexpected error.",
    );
  });

  it("reports tier2 success too, styled as ok", async () => {
    mockedTest.mockResolvedValue({ ok: true, detail: "Tier 2 reachable." });
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="tier2-test"]').trigger("click");
    await flushPromises();
    const result = wrapper.find('[data-testid="tier2-test-result"]');
    expect(result.text()).toContain("Tier 2 reachable.");
    expect(result.classes()).toContain("ok");
  });

  it("sends a freshly typed key rather than falling back to the saved one", async () => {
    mockedTest.mockResolvedValue({ ok: true, detail: null });
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="tier1-api-key"] input').setValue("sk-fresh");
    await wrapper.find('[data-testid="tier1-test"]').trigger("click");
    await flushPromises();
    expect(mockedTest).toHaveBeenCalledWith(expect.objectContaining({ api_key: "sk-fresh" }));
  });
});

describe("SettingsAiProviderPanel field edits", () => {
  beforeEach(() => {
    mockedGet.mockResolvedValue(baseSettings);
  });

  it("edits tier1 model/base-url and tier2 model/base-url/provider/key, saving all of it", async () => {
    mockedUpdate.mockResolvedValue(baseSettings);
    const wrapper = mountPanel();
    await flushPromises();

    await wrapper.find('[data-testid="tier1-model"]').setValue("gpt-4o");
    await wrapper.find('[data-testid="tier1-base-url"]').setValue("https://tier1.example.com");
    await wrapper.find('[data-testid="tier2-model"]').setValue("claude-opus-5");
    await wrapper.find('[data-testid="tier2-base-url"]').setValue("https://tier2.example.com");
    await wrapper.find('[data-testid="tier2-api-key"] input').setValue("tier2-fresh-key");

    const selects = wrapper.findAllComponents(Select);
    await selects[1]!.vm.$emit("update:modelValue", "moondream_cloud");
    await flushPromises();

    await wrapper.find('[data-testid="ai-provider-form"]').trigger("submit.prevent");
    await flushPromises();

    expect(mockedUpdate).toHaveBeenCalledWith(
      expect.objectContaining({
        tier1_model: "gpt-4o",
        tier1_base_url: "https://tier1.example.com",
        tier2_model: "claude-opus-5",
        tier2_base_url: "https://tier2.example.com",
        tier2_provider: "moondream_cloud",
        tier2_api_key: "tier2-fresh-key",
      }),
    );
  });

  it("saves null for tier2 model/base-url when left blank", async () => {
    mockedGet.mockResolvedValue(emptySettings);
    mockedUpdate.mockResolvedValue(emptySettings);
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="ai-provider-form"]').trigger("submit.prevent");
    await flushPromises();
    expect(mockedUpdate).toHaveBeenCalledWith(
      expect.objectContaining({ tier2_model: null, tier2_base_url: null }),
    );
  });

  it("clears a saved tier2 key via its checkbox", async () => {
    mockedGet.mockResolvedValue({ ...baseSettings, tier2_api_key_set: true });
    mockedUpdate.mockResolvedValue(baseSettings);
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="tier2-clear-key"]').setValue(true);
    await wrapper.find('[data-testid="ai-provider-form"]').trigger("submit.prevent");
    await flushPromises();
    expect(mockedUpdate).toHaveBeenCalledWith(expect.objectContaining({ tier2_api_key: "" }));
  });

  it("adjusts the tuning number fields and saves the new values", async () => {
    mockedUpdate.mockResolvedValue(baseSettings);
    const wrapper = mountPanel();
    await flushPromises();

    const numbers = wrapper.findAllComponents(InputNumber);
    await numbers[0]!.vm.$emit("update:modelValue", 8);
    await numbers[1]!.vm.$emit("update:modelValue", 0.75);
    await numbers[2]!.vm.$emit("update:modelValue", 10);
    await flushPromises();

    await wrapper.find('[data-testid="ai-provider-form"]').trigger("submit.prevent");
    await flushPromises();

    expect(mockedUpdate).toHaveBeenCalledWith(
      expect.objectContaining({
        keyframes_per_clip: 8,
        tier2_suspicion_threshold: 0.75,
        feedback_context_count: 10,
      }),
    );
  });
});
