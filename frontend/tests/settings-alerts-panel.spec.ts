import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import InputNumber from "primevue/inputnumber";
import ToggleSwitch from "primevue/toggleswitch";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/client";
import SettingsAlertsPanel from "@/components/SettingsAlertsPanel.vue";
import { makePinia, mountGlobal } from "./helpers";

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  getAlertSettings: vi.fn(),
  updateAlertSettings: vi.fn(),
  testAlertChannels: vi.fn(),
}));

const toastAdd = vi.fn();
vi.mock("primevue/usetoast", () => ({
  useToast: () => ({ add: toastAdd }),
}));

import { getAlertSettings, testAlertChannels, updateAlertSettings } from "@/api";

const mockedGet = vi.mocked(getAlertSettings);
const mockedUpdate = vi.mocked(updateAlertSettings);
const mockedTest = vi.mocked(testAlertChannels);

const baseSettings = {
  discord_enabled: true,
  discord_webhook_set: true,
  slack_enabled: true,
  slack_webhook_set: false,
  smtp_enabled: true,
  smtp_host: "smtp.example.com",
  smtp_port: 587,
  smtp_username: "alerts",
  smtp_password_set: true,
  smtp_use_tls: true,
  smtp_from_address: "alerts@example.com",
  smtp_to_addresses: ["a@example.com", "b@example.com"],
  alert_on_suspicious_clip: true,
  suspicion_alert_threshold: 0.5,
  alert_on_vehicle_proximity: true,
  quiet_hours_start: "22:00:00",
  quiet_hours_end: "07:00:00",
  dedup_window_minutes: 15,
};

const emptySettings = {
  discord_enabled: false,
  discord_webhook_set: false,
  slack_enabled: false,
  slack_webhook_set: false,
  smtp_enabled: false,
  smtp_host: null,
  smtp_port: 587,
  smtp_username: null,
  smtp_password_set: false,
  smtp_use_tls: true,
  smtp_from_address: null,
  smtp_to_addresses: [],
  alert_on_suspicious_clip: true,
  alert_on_vehicle_proximity: true,
  suspicion_alert_threshold: 0.5,
  quiet_hours_start: null,
  quiet_hours_end: null,
  dedup_window_minutes: 15,
};

beforeEach(() => {
  vi.clearAllMocks();
});

function mountPanel() {
  return mount(SettingsAlertsPanel, { global: mountGlobal(makePinia()) });
}

function byTestId<T>(
  wrapper: VueWrapper,
  component: new () => T,
  testid: string,
): VueWrapper<T> {
  return wrapper
    .findAllComponents(component as never)
    .find((c) => c.attributes("data-testid") === testid) as unknown as VueWrapper<T>;
}

describe("SettingsAlertsPanel loading", () => {
  it("shows a loading skeleton while fetching", () => {
    mockedGet.mockReturnValue(new Promise(() => {}));
    const wrapper = mountPanel();
    expect(wrapper.find('[data-testid="alerts-loading"]').exists()).toBe(true);
  });

  it("shows the API error message when loading fails", async () => {
    mockedGet.mockRejectedValue(new ApiError(500, "Server exploded"));
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find('[data-testid="alerts-load-error"]').text()).toBe("Server exploded");
  });

  it("falls back to a generic load error for non-API failures", async () => {
    mockedGet.mockRejectedValue(new TypeError("down"));
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find('[data-testid="alerts-load-error"]').text()).toBe(
      "Could not load alert settings.",
    );
  });

  it("populates fields, joining addresses and trimming quiet hours to HH:MM", async () => {
    mockedGet.mockResolvedValue(baseSettings);
    const wrapper = mountPanel();
    await flushPromises();

    const toAddresses = wrapper.find('[data-testid="smtp-to-addresses"]')
      .element as HTMLTextAreaElement;
    expect(toAddresses.value).toBe("a@example.com, b@example.com");

    const start = wrapper.find('[data-testid="quiet-hours-start"]').element as HTMLInputElement;
    expect(start.value).toBe("22:00");
    const end = wrapper.find('[data-testid="quiet-hours-end"]').element as HTMLInputElement;
    expect(end.value).toBe("07:00");

    const discordKey = wrapper.find('[data-testid="discord-webhook"] input')
      .element as HTMLInputElement;
    expect(discordKey.placeholder).toContain("saved");
    const slackKey = wrapper.find('[data-testid="slack-webhook"] input')
      .element as HTMLInputElement;
    expect(slackKey.placeholder).not.toContain("saved");
  });

  it("hides channel detail fields and threshold field when their toggles are off", async () => {
    mockedGet.mockResolvedValue(emptySettings);
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find('[data-testid="discord-webhook"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="slack-webhook"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="smtp-host"]').exists()).toBe(false);
  });
});

describe("SettingsAlertsPanel save", () => {
  beforeEach(() => {
    mockedGet.mockResolvedValue(baseSettings);
  });

  it("saves unchanged (null) secrets when nothing new was typed", async () => {
    mockedUpdate.mockResolvedValue(baseSettings);
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="alerts-form"]').trigger("submit.prevent");
    await flushPromises();
    expect(mockedUpdate).toHaveBeenCalledWith(
      expect.objectContaining({
        discord_webhook_url: null,
        slack_webhook_url: null,
        smtp_password: null,
        smtp_to_addresses: ["a@example.com", "b@example.com"],
        quiet_hours_start: "22:00",
        quiet_hours_end: "07:00",
      }),
    );
    expect(toastAdd).toHaveBeenCalledWith(expect.objectContaining({ severity: "success" }));
  });

  it("sends freshly typed secrets and clears their inputs afterwards", async () => {
    mockedUpdate.mockResolvedValue(baseSettings);
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="discord-webhook"] input').setValue("https://discord/new");
    await wrapper.find('[data-testid="slack-webhook"] input').setValue("https://slack/new");
    await wrapper.find('[data-testid="smtp-password"] input').setValue("new-pass");
    await wrapper.find('[data-testid="alerts-form"]').trigger("submit.prevent");
    await flushPromises();
    expect(mockedUpdate).toHaveBeenCalledWith(
      expect.objectContaining({
        discord_webhook_url: "https://discord/new",
        slack_webhook_url: "https://slack/new",
        smtp_password: "new-pass",
      }),
    );
    const discordInput = wrapper.find('[data-testid="discord-webhook"] input')
      .element as HTMLInputElement;
    expect(discordInput.value).toBe("");
  });

  it("clears saved secrets via their checkboxes without typing new ones", async () => {
    mockedUpdate.mockResolvedValue({
      ...baseSettings,
      discord_webhook_set: false,
      smtp_password_set: false,
    });
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="discord-clear-webhook"]').setValue(true);
    await wrapper.find('[data-testid="smtp-clear-password"]').setValue(true);
    await wrapper.find('[data-testid="alerts-form"]').trigger("submit.prevent");
    await flushPromises();
    expect(mockedUpdate).toHaveBeenCalledWith(
      expect.objectContaining({ discord_webhook_url: "", smtp_password: "" }),
    );
  });

  it("clears a saved slack webhook via its checkbox", async () => {
    mockedGet.mockResolvedValue({ ...baseSettings, slack_webhook_set: true });
    mockedUpdate.mockResolvedValue(baseSettings);
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="slack-clear-webhook"]').setValue(true);
    await wrapper.find('[data-testid="alerts-form"]').trigger("submit.prevent");
    await flushPromises();
    expect(mockedUpdate).toHaveBeenCalledWith(expect.objectContaining({ slack_webhook_url: "" }));
  });

  it("parses the to-addresses textarea, trimming and dropping blanks", async () => {
    mockedUpdate.mockResolvedValue(baseSettings);
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper
      .find('[data-testid="smtp-to-addresses"]')
      .setValue(" first@example.com ,, second@example.com ,");
    await wrapper.find('[data-testid="alerts-form"]').trigger("submit.prevent");
    await flushPromises();
    expect(mockedUpdate).toHaveBeenCalledWith(
      expect.objectContaining({ smtp_to_addresses: ["first@example.com", "second@example.com"] }),
    );
  });

  it("sends null for host/username/from-address and empty quiet hours when blanked out", async () => {
    mockedGet.mockResolvedValue(emptySettings);
    mockedUpdate.mockResolvedValue(emptySettings);
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="alerts-form"]').trigger("submit.prevent");
    await flushPromises();
    expect(mockedUpdate).toHaveBeenCalledWith(
      expect.objectContaining({
        smtp_host: null,
        smtp_username: null,
        smtp_from_address: null,
        smtp_to_addresses: [],
        quiet_hours_start: null,
        quiet_hours_end: null,
      }),
    );
  });

  it("enables every channel from scratch and fills in its fields, plus rules/quiet-hours/dedup", async () => {
    mockedGet.mockResolvedValue(emptySettings);
    mockedUpdate.mockResolvedValue(emptySettings);
    const wrapper = mountPanel();
    await flushPromises();

    await byTestId(wrapper, ToggleSwitch, "discord-enabled").vm.$emit("update:modelValue", true);
    await byTestId(wrapper, ToggleSwitch, "slack-enabled").vm.$emit("update:modelValue", true);
    await byTestId(wrapper, ToggleSwitch, "smtp-enabled").vm.$emit("update:modelValue", true);
    await flushPromises();

    await wrapper.find('[data-testid="smtp-host"]').setValue("smtp.new.example.com");
    await wrapper.find('[data-testid="smtp-username"]').setValue("newuser");
    await wrapper.find('[data-testid="smtp-from-address"]').setValue("new@example.com");
    await byTestId(wrapper, InputNumber, "smtp-port").vm.$emit("update:modelValue", 2525);
    await byTestId(wrapper, ToggleSwitch, "smtp-use-tls").vm.$emit("update:modelValue", false);
    await byTestId(wrapper, InputNumber, "suspicion-alert-threshold").vm.$emit(
      "update:modelValue",
      0.8,
    );
    await byTestId(wrapper, ToggleSwitch, "alert-on-proximity").vm.$emit(
      "update:modelValue",
      false,
    );
    await wrapper.find('[data-testid="quiet-hours-start"]').setValue("23:00");
    await wrapper.find('[data-testid="quiet-hours-end"]').setValue("06:00");
    await byTestId(wrapper, InputNumber, "dedup-window").vm.$emit("update:modelValue", 30);
    await flushPromises();

    await wrapper.find('[data-testid="alerts-form"]').trigger("submit.prevent");
    await flushPromises();

    expect(mockedUpdate).toHaveBeenCalledWith({
      discord_enabled: true,
      discord_webhook_url: null,
      slack_enabled: true,
      slack_webhook_url: null,
      smtp_enabled: true,
      smtp_host: "smtp.new.example.com",
      smtp_port: 2525,
      smtp_username: "newuser",
      smtp_password: null,
      smtp_use_tls: false,
      smtp_from_address: "new@example.com",
      smtp_to_addresses: [],
      alert_on_suspicious_clip: true,
      suspicion_alert_threshold: 0.8,
      alert_on_vehicle_proximity: false,
      quiet_hours_start: "23:00",
      quiet_hours_end: "06:00",
      dedup_window_minutes: 30,
    });
  });

  it("shows the API error message when saving fails", async () => {
    mockedUpdate.mockRejectedValue(new ApiError(400, "Invalid SMTP host."));
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="alerts-form"]').trigger("submit.prevent");
    await flushPromises();
    expect(wrapper.find('[data-testid="alerts-save-error"]').text()).toBe("Invalid SMTP host.");
  });

  it("falls back to a generic save error for non-API failures", async () => {
    mockedUpdate.mockRejectedValue(new TypeError("down"));
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="alerts-form"]').trigger("submit.prevent");
    await flushPromises();
    expect(wrapper.find('[data-testid="alerts-save-error"]').text()).toBe("Unexpected error.");
  });

  it("toggles the suspicion-alert threshold field's visibility", async () => {
    const wrapper = mountPanel();
    await flushPromises();
    expect(wrapper.find('[data-testid="suspicion-alert-threshold"]').exists()).toBe(true);
    const toggles = wrapper.findAllComponents(ToggleSwitch);
    const suspiciousToggle = toggles.find(
      (t) => t.attributes("data-testid") === "alert-on-suspicious",
    );
    await suspiciousToggle!.vm.$emit("update:modelValue", false);
    await flushPromises();
    expect(wrapper.find('[data-testid="suspicion-alert-threshold"]').exists()).toBe(false);
  });
});

describe("SettingsAlertsPanel test channels", () => {
  beforeEach(() => {
    mockedGet.mockResolvedValue(baseSettings);
  });

  it("renders a row per channel present in the response", async () => {
    mockedTest.mockResolvedValue({
      discord: { ok: true, detail: "Sent." },
      slack: { ok: false, detail: "Webhook rejected." },
    });
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="test-alerts"]').trigger("click");
    await flushPromises();
    const results = wrapper.find('[data-testid="test-results"]');
    expect(results.text()).toContain("Discord");
    expect(results.text()).toContain("Sent.");
    expect(results.text()).toContain("Slack");
    expect(results.text()).toContain("Webhook rejected.");
    expect(results.text()).not.toContain("Email");
  });

  it("renders the email row when smtp is present", async () => {
    mockedTest.mockResolvedValue({ smtp: { ok: true, detail: "Delivered." } });
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="test-alerts"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="test-results"]').text()).toContain("Email");
  });

  it("shows no results block when the response has no channels", async () => {
    mockedTest.mockResolvedValue({});
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="test-alerts"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="test-results"]').exists()).toBe(false);
  });

  it("toasts an error when the test call itself throws", async () => {
    mockedTest.mockRejectedValue(new ApiError(400, "No channels configured."));
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="test-alerts"]').trigger("click");
    await flushPromises();
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "error", detail: "No channels configured." }),
    );
  });

  it("toasts a generic error for a non-API test failure", async () => {
    mockedTest.mockRejectedValue(new TypeError("down"));
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.find('[data-testid="test-alerts"]').trigger("click");
    await flushPromises();
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "error", detail: "Unexpected error." }),
    );
  });
});
