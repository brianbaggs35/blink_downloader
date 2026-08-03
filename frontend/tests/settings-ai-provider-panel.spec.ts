import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import AutoComplete from "primevue/autocomplete";
import Checkbox from "primevue/checkbox";
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
  testAiAnalysis: vi.fn(),
  listAiModels: vi.fn(),
}));

const toastAdd = vi.fn();
vi.mock("primevue/usetoast", () => ({
  useToast: () => ({ add: toastAdd }),
}));

import {
  getAiSettings,
  listAiModels,
  testAiAnalysis,
  testAiConnection,
  updateAiSettings,
} from "@/api";

const mockedGet = vi.mocked(getAiSettings);
const mockedUpdate = vi.mocked(updateAiSettings);
const mockedTest = vi.mocked(testAiConnection);
const mockedTestAnalysis = vi.mocked(testAiAnalysis);
const mockedListModels = vi.mocked(listAiModels);

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
  tier2_linked_to_tier1: false,
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
  tier2_linked_to_tier1: false,
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

function byTestId<T>(wrapper: VueWrapper, component: new () => T, testid: string): VueWrapper<T> {
  return wrapper
    .findAllComponents(component as never)
    .find((c) => c.attributes("data-testid") === testid) as unknown as VueWrapper<T>;
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
    await byTestId(wrapper, Checkbox, "tier1-clear-key").vm.$emit("update:modelValue", true);
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

describe("SettingsAiProviderPanel test analysis", () => {
  beforeEach(() => {
    mockedGet.mockResolvedValue(baseSettings);
  });

  it("requires a provider and model before testing", async () => {
    mockedGet.mockResolvedValue(emptySettings);
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="tier1-test-analysis"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="tier1-test-analysis-result"]').text()).toContain(
      "Choose a provider and model first.",
    );
    expect(mockedTestAnalysis).not.toHaveBeenCalled();
  });

  it("reports a real analysis result on success", async () => {
    mockedTestAnalysis.mockResolvedValue({ ok: true, detail: 'Model responded: "All clear."' });
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="tier1-test-analysis"]').trigger("click");
    await flushPromises();
    expect(mockedTestAnalysis).toHaveBeenCalledWith({
      tier: "tier1",
      provider: "openai",
      model: "gpt-4o-mini",
      api_key: null,
      base_url: null,
    });
    const result = wrapper.find('[data-testid="tier1-test-analysis-result"]');
    expect(result.text()).toContain("All clear.");
    expect(result.classes()).toContain("ok");
  });

  it("reports tier2 analysis success, styled as ok", async () => {
    mockedTestAnalysis.mockResolvedValue({ ok: true, detail: "Tier 2 responded fine." });
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="tier2-test-analysis"]').trigger("click");
    await flushPromises();
    const result = wrapper.find('[data-testid="tier2-test-analysis-result"]');
    expect(result.text()).toContain("Tier 2 responded fine.");
    expect(result.classes()).toContain("ok");
  });

  it("reports tier2 analysis failure, styled as failing", async () => {
    mockedTestAnalysis.mockResolvedValue({ ok: false, detail: "Model rejected the request." });
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="tier2-test-analysis"]').trigger("click");
    await flushPromises();
    const result = wrapper.find('[data-testid="tier2-test-analysis-result"]');
    expect(result.text()).toContain("Model rejected the request.");
    expect(result.classes()).toContain("fail");
  });

  it("shows the API error message when the analysis test call itself throws", async () => {
    mockedTestAnalysis.mockRejectedValue(new ApiError(401, "Unauthorized."));
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="tier1-test-analysis"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="tier1-test-analysis-result"]').text()).toContain(
      "Unauthorized.",
    );
  });
});

describe("SettingsAiProviderPanel field edits", () => {
  beforeEach(() => {
    mockedGet.mockResolvedValue(baseSettings);
  });

  it("edits tier1/tier2 model, provider, and key, saving all of it - base URL stays null for cloud providers", async () => {
    mockedUpdate.mockResolvedValue(baseSettings);
    const wrapper = mountPanel();
    await flushPromises();

    await wrapper.find('[data-testid="tier1-model"]').setValue("gpt-4o");
    await wrapper.find('[data-testid="tier2-model"]').setValue("claude-opus-5");
    await wrapper.find('[data-testid="tier2-api-key"] input').setValue("tier2-fresh-key");

    const selects = wrapper.findAllComponents(Select);
    await selects[1]!.vm.$emit("update:modelValue", "moondream_cloud");
    await flushPromises();

    await wrapper.find('[data-testid="ai-provider-form"]').trigger("submit.prevent");
    await flushPromises();

    expect(mockedUpdate).toHaveBeenCalledWith(
      expect.objectContaining({
        tier1_model: "gpt-4o",
        tier1_base_url: null, // openai (tier1's provider here) is cloud
        tier2_model: "claude-opus-5",
        tier2_base_url: null, // moondream_cloud is cloud too
        tier2_provider: "moondream_cloud",
        tier2_api_key: "tier2-fresh-key",
      }),
    );
  });

  it("shows and saves a base URL for self-hosted providers, and clears it when switching to a cloud provider", async () => {
    mockedUpdate.mockResolvedValue(baseSettings);
    const wrapper = mountPanel();
    await flushPromises();

    const selects = wrapper.findAllComponents(Select);
    await selects[0]!.vm.$emit("update:modelValue", "ollama");
    await selects[1]!.vm.$emit("update:modelValue", "moondream");
    await flushPromises();

    await wrapper.find('[data-testid="tier1-base-url"]').setValue("https://tier1.example.com");
    await wrapper.find('[data-testid="tier2-base-url"]').setValue("https://tier2.example.com");

    await wrapper.find('[data-testid="ai-provider-form"]').trigger("submit.prevent");
    await flushPromises();
    expect(mockedUpdate).toHaveBeenCalledWith(
      expect.objectContaining({
        tier1_base_url: "https://tier1.example.com",
        tier2_base_url: "https://tier2.example.com",
      }),
    );

    // Switching to a cloud provider hides the field and drops its value.
    await selects[0]!.vm.$emit("update:modelValue", "openai");
    await flushPromises();
    expect(wrapper.find('[data-testid="tier1-base-url"]').exists()).toBe(false);

    await wrapper.find('[data-testid="ai-provider-form"]').trigger("submit.prevent");
    await flushPromises();
    expect(mockedUpdate).toHaveBeenLastCalledWith(
      expect.objectContaining({ tier1_base_url: null }),
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
    await byTestId(wrapper, Checkbox, "tier2-clear-key").vm.$emit("update:modelValue", true);
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

describe("SettingsAiProviderPanel tier2 linked to tier1", () => {
  it("loads the linked flag and disables the toggle without a tier1 provider", async () => {
    mockedGet.mockResolvedValue({ ...emptySettings, tier2_linked_to_tier1: true });
    const wrapper = mountPanel();
    await flushPromises();
    const toggle = byTestId(wrapper, ToggleSwitch, "tier2-link-to-tier1");
    expect(toggle.props("modelValue")).toBe(true);
    expect(toggle.props("disabled")).toBe(true);
  });

  it("hides tier2's own provider/key/base-url fields and shows a status note when linked", async () => {
    mockedGet.mockResolvedValue({ ...baseSettings, tier2_linked_to_tier1: true });
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find('[data-testid="tier2-provider"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="tier2-api-key"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="tier2-linked-note"]').text()).toContain("OpenAI");
  });

  it("saves tier2_linked_to_tier1 and force-unlinks when tier1's provider is cleared", async () => {
    mockedUpdate.mockResolvedValue(baseSettings);
    const wrapper = mountPanel();
    await flushPromises();

    await byTestId(wrapper, ToggleSwitch, "tier2-link-to-tier1").vm.$emit(
      "update:modelValue",
      true,
    );
    await flushPromises();
    await wrapper.find('[data-testid="ai-provider-form"]').trigger("submit.prevent");
    await flushPromises();
    expect(mockedUpdate).toHaveBeenCalledWith(
      expect.objectContaining({ tier2_linked_to_tier1: true }),
    );

    const selects = wrapper.findAllComponents(Select);
    await selects[0]!.vm.$emit("update:modelValue", null);
    await flushPromises();
    expect(byTestId(wrapper, ToggleSwitch, "tier2-link-to-tier1").props("modelValue")).toBe(false);
  });

  it("routes tier2's connection test through tier1's live credentials when linked", async () => {
    mockedGet.mockResolvedValue({ ...baseSettings, tier2_linked_to_tier1: true });
    mockedTest.mockResolvedValue({ ok: true, detail: "Connected." });
    const wrapper = mountPanel();
    await flushPromises();

    await wrapper.find('[data-testid="tier2-test"]').trigger("click");
    await flushPromises();
    expect(mockedTest).toHaveBeenCalledWith(
      expect.objectContaining({ tier: "tier1", provider: "openai" }),
    );
  });
});

describe("SettingsAiProviderPanel model suggestions", () => {
  it("filters tier1 model suggestions from the static catalog via the complete event", async () => {
    mockedGet.mockResolvedValue(baseSettings);
    const wrapper = mountPanel();
    await flushPromises();

    const autocompletes = wrapper.findAllComponents(AutoComplete);
    await autocompletes[0]!.vm.$emit("complete", { query: "gpt-5" });
    await flushPromises();
    const suggestions = autocompletes[0]!.props("suggestions") as string[];
    expect(suggestions).toContain("gpt-5-nano");
    expect(suggestions).toContain("gpt-5.4-mini");
    expect(suggestions).toContain("gpt-5.4-nano");
    expect(suggestions).not.toContain("claude-opus-5");
  });

  it("returns no suggestions when no provider is chosen yet", async () => {
    mockedGet.mockResolvedValue(emptySettings);
    const wrapper = mountPanel();
    await flushPromises();

    const autocompletes = wrapper.findAllComponents(AutoComplete);
    await autocompletes[0]!.vm.$emit("complete", { query: "" });
    await flushPromises();
    expect(autocompletes[0]!.props("suggestions")).toEqual([]);
  });

  it("filters tier2's suggestions from tier1's provider when linked", async () => {
    mockedGet.mockResolvedValue({ ...baseSettings, tier2_linked_to_tier1: true });
    const wrapper = mountPanel();
    await flushPromises();

    const autocompletes = wrapper.findAllComponents(AutoComplete);
    await autocompletes[1]!.vm.$emit("complete", { query: "" });
    await flushPromises();
    // tier2 is linked, so its suggestions come from tier1's provider (openai), not anthropic
    expect(autocompletes[1]!.props("suggestions")).toEqual(
      expect.arrayContaining(["gpt-4o", "gpt-5"]),
    );
  });
});

describe("SettingsAiProviderPanel fetch models (Ollama)", () => {
  it("only shows the fetch-models button for ollama-family providers", async () => {
    mockedGet.mockResolvedValue(baseSettings);
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find('[data-testid="tier1-fetch-models"]').exists()).toBe(false);

    const selects = wrapper.findAllComponents(Select);
    await selects[0]!.vm.$emit("update:modelValue", "ollama");
    await flushPromises();
    expect(wrapper.find('[data-testid="tier1-fetch-models"]').exists()).toBe(true);
  });

  it("fetches models and feeds them into the AutoComplete suggestions, overriding the static list", async () => {
    mockedGet.mockResolvedValue({ ...baseSettings, tier1_provider: "ollama" as const });
    mockedListModels.mockResolvedValue({ ok: true, models: ["llava:latest", "custom-model"] });
    const wrapper = mountPanel();
    await flushPromises();

    await wrapper.find('[data-testid="tier1-fetch-models"]').trigger("click");
    await flushPromises();
    expect(mockedListModels).toHaveBeenCalledWith(
      expect.objectContaining({ tier: "tier1", provider: "ollama" }),
    );

    const autocompletes = wrapper.findAllComponents(AutoComplete);
    await autocompletes[0]!.vm.$emit("complete", { query: "" });
    await flushPromises();
    expect(autocompletes[0]!.props("suggestions")).toEqual(["llava:latest", "custom-model"]);
  });

  it("shows the server's error detail when fetching models fails", async () => {
    mockedGet.mockResolvedValue({ ...baseSettings, tier1_provider: "ollama" as const });
    mockedListModels.mockResolvedValue({ ok: false, detail: "Could not reach Ollama." });
    const wrapper = mountPanel();
    await flushPromises();

    await wrapper.find('[data-testid="tier1-fetch-models"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="tier1-fetch-models-error"]').text()).toBe(
      "Could not reach Ollama.",
    );
  });

  it("falls back to a generic error for a non-API failure", async () => {
    mockedGet.mockResolvedValue({ ...baseSettings, tier1_provider: "ollama" as const });
    mockedListModels.mockRejectedValue(new TypeError("network down"));
    const wrapper = mountPanel();
    await flushPromises();

    await wrapper.find('[data-testid="tier1-fetch-models"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="tier1-fetch-models-error"]').text()).toBe(
      "Could not fetch models.",
    );
  });

  it("surfaces an ApiError's message when the fetch call itself throws", async () => {
    mockedGet.mockResolvedValue({ ...baseSettings, tier1_provider: "ollama" as const });
    mockedListModels.mockRejectedValue(new ApiError(500, "Server exploded"));
    const wrapper = mountPanel();
    await flushPromises();

    await wrapper.find('[data-testid="tier1-fetch-models"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="tier1-fetch-models-error"]').text()).toBe(
      "Server exploded",
    );
  });

  it("falls back to a generic detail when the server omits one on failure", async () => {
    mockedGet.mockResolvedValue({ ...baseSettings, tier1_provider: "ollama" as const });
    mockedListModels.mockResolvedValue({ ok: false });
    const wrapper = mountPanel();
    await flushPromises();

    await wrapper.find('[data-testid="tier1-fetch-models"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="tier1-fetch-models-error"]').text()).toBe(
      "Could not fetch models.",
    );
  });

  it("treats a missing models array on success as empty", async () => {
    mockedGet.mockResolvedValue({ ...baseSettings, tier1_provider: "ollama" as const });
    mockedListModels.mockResolvedValue({ ok: true });
    const wrapper = mountPanel();
    await flushPromises();

    await wrapper.find('[data-testid="tier1-fetch-models"]').trigger("click");
    await flushPromises();
    const autocompletes = wrapper.findAllComponents(AutoComplete);
    await autocompletes[0]!.vm.$emit("complete", { query: "" });
    await flushPromises();
    expect(autocompletes[0]!.props("suggestions")).toEqual([]);
  });

  it("fetches tier2 models using tier1's credentials when linked", async () => {
    mockedGet.mockResolvedValue({
      ...baseSettings,
      tier1_provider: "ollama" as const,
      tier2_linked_to_tier1: true,
    });
    mockedListModels.mockResolvedValue({ ok: true, models: ["llava:latest"] });
    const wrapper = mountPanel();
    await flushPromises();

    expect(wrapper.find('[data-testid="tier2-fetch-models"]').exists()).toBe(true);
    await wrapper.find('[data-testid="tier2-fetch-models"]').trigger("click");
    await flushPromises();
    expect(mockedListModels).toHaveBeenCalledWith(
      expect.objectContaining({ tier: "tier1", provider: "ollama" }),
    );
  });

  it("shows tier2's own fetch-models error independently of tier1's", async () => {
    mockedGet.mockResolvedValue({
      ...baseSettings,
      tier1_provider: "ollama" as const,
      tier2_provider: "ollama_cloud" as const,
    });
    mockedListModels.mockResolvedValue({ ok: false, detail: "Tier 2 fetch failed." });
    const wrapper = mountPanel();
    await flushPromises();

    await wrapper.find('[data-testid="tier2-fetch-models"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="tier2-fetch-models-error"]').text()).toBe(
      "Tier 2 fetch failed.",
    );
    expect(wrapper.find('[data-testid="tier1-fetch-models-error"]').exists()).toBe(false);
  });

  it("resets any fetched models when the provider changes", async () => {
    mockedGet.mockResolvedValue({ ...baseSettings, tier1_provider: "ollama" as const });
    mockedListModels.mockResolvedValue({ ok: true, models: ["llava:latest"] });
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="tier1-fetch-models"]').trigger("click");
    await flushPromises();

    const selects = wrapper.findAllComponents(Select);
    await selects[0]!.vm.$emit("update:modelValue", "moondream");
    await flushPromises();

    const autocompletes = wrapper.findAllComponents(AutoComplete);
    await autocompletes[0]!.vm.$emit("complete", { query: "" });
    await flushPromises();
    // Falls back to moondream's static catalog, not the stale ollama fetch.
    expect(autocompletes[0]!.props("suggestions")).toEqual(
      expect.arrayContaining(["moondream2"]),
    );
  });
});
