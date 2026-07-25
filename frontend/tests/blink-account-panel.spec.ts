import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";

vi.mock("@/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api")>()),
  getBlinkStatus: vi.fn(),
  linkBlinkAccount: vi.fn(),
  verifyBlinkAccount: vi.fn(),
  triggerBlinkSync: vi.fn(),
  unlinkBlinkAccount: vi.fn(),
}));

const toastAdd = vi.fn();
vi.mock("primevue/usetoast", () => ({ useToast: () => ({ add: toastAdd }) }));

import {
  getBlinkStatus,
  linkBlinkAccount,
  triggerBlinkSync,
  unlinkBlinkAccount,
  verifyBlinkAccount,
} from "@/api";
import { ApiError } from "@/api/client";
import BlinkAccountPanel from "@/components/BlinkAccountPanel.vue";
import { makePinia, mountGlobal } from "./helpers";

const mockedStatus = vi.mocked(getBlinkStatus);
const mockedLink = vi.mocked(linkBlinkAccount);
const mockedVerify = vi.mocked(verifyBlinkAccount);
const mockedSync = vi.mocked(triggerBlinkSync);
const mockedUnlink = vi.mocked(unlinkBlinkAccount);

const linkedStatus = {
  linked: true,
  status: "active" as const,
  last_sync: "2026-07-20T12:00:00Z",
  last_error: null,
  camera_count: 3,
};

function unlinkedStatus() {
  return { linked: false, status: null, last_sync: null, last_error: null, camera_count: 0 };
}

async function mountPanel() {
  const wrapper = mount(BlinkAccountPanel, {
    global: mountGlobal(makePinia()),
    attachTo: document.body,
  });
  await flushPromises();
  return wrapper;
}

beforeEach(() => {
  vi.clearAllMocks();
  document.body.innerHTML = "";
  mockedStatus.mockResolvedValue(unlinkedStatus());
});

describe("BlinkAccountPanel — status check failure", () => {
  it("shows a retry state instead of the sign-in form when the status check fails", async () => {
    mockedStatus.mockRejectedValue(new TypeError("network down"));
    const wrapper = await mountPanel();

    expect(wrapper.find('[data-testid="blink-status-error"]').text()).toContain(
      "Could not check your Blink connection status.",
    );
    expect(wrapper.find('[data-testid="blink-link-form"]').exists()).toBe(false);
  });

  it("retries the status check and shows the linked view on success", async () => {
    mockedStatus.mockRejectedValueOnce(new TypeError("network down")).mockResolvedValue(linkedStatus);
    const wrapper = await mountPanel();
    expect(wrapper.find('[data-testid="blink-status-error"]').exists()).toBe(true);

    await wrapper.find('[data-testid="retry-status"]').trigger("click");
    await flushPromises();

    expect(wrapper.find('[data-testid="blink-status-error"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="blink-linked"]').exists()).toBe(true);
  });
});

describe("BlinkAccountPanel — unlinked", () => {
  it("shows the sign-in form once status loads", async () => {
    const wrapper = await mountPanel();
    expect(wrapper.find('[data-testid="blink-link-form"]').exists()).toBe(true);
  });

  it("signs in successfully without 2FA", async () => {
    mockedLink.mockResolvedValue({ status: "linked", link_session_id: null });
    mockedStatus.mockResolvedValueOnce(unlinkedStatus()).mockResolvedValue(linkedStatus);
    const wrapper = await mountPanel();

    await wrapper.find('[data-testid="blink-username"]').setValue("brian@example.com");
    await wrapper.find('[data-testid="blink-password"] input').setValue("hunter2");
    await wrapper.find('[data-testid="blink-sign-in"]').trigger("click");
    await flushPromises();

    expect(mockedLink).toHaveBeenCalledWith("brian@example.com", "hunter2");
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ summary: "Blink account linked" }),
    );
    expect(wrapper.find('[data-testid="blink-linked"]').exists()).toBe(true);
  });

  it("shows an inline error for rejected credentials", async () => {
    mockedLink.mockRejectedValue(new ApiError(400, "Blink rejected that username or password."));
    const wrapper = await mountPanel();
    await wrapper.find('[data-testid="blink-username"]').setValue("brian@example.com");
    await wrapper.find('[data-testid="blink-password"] input').setValue("wrong");
    await wrapper.find('[data-testid="blink-sign-in"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="link-error"]').text()).toBe(
      "Blink rejected that username or password.",
    );
  });

  it("falls back to a generic error for non-API failures", async () => {
    mockedLink.mockRejectedValue(new TypeError("network down"));
    const wrapper = await mountPanel();
    await wrapper.find('[data-testid="blink-username"]').setValue("brian@example.com");
    await wrapper.find('[data-testid="blink-password"] input').setValue("hunter2");
    await wrapper.find('[data-testid="blink-sign-in"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="link-error"]').text()).toContain(
      "Could not reach the server",
    );
  });

  it("opens the 2FA modal when Blink requires verification", async () => {
    mockedLink.mockResolvedValue({ status: "verification_required", link_session_id: "sess-1" });
    const wrapper = await mountPanel();
    await wrapper.find('[data-testid="blink-username"]').setValue("brian@example.com");
    await wrapper.find('[data-testid="blink-password"] input').setValue("hunter2");
    await wrapper.find('[data-testid="blink-sign-in"]').trigger("click");
    await flushPromises();
    await nextTick();
    await flushPromises();
    expect(document.body.querySelector('[data-testid="twofa-modal"]')).toBeTruthy();
  });

  it("completes the 2FA flow and closes the modal", async () => {
    mockedLink.mockResolvedValue({ status: "verification_required", link_session_id: "sess-1" });
    mockedVerify.mockResolvedValue({ status: "linked", link_session_id: null });
    mockedStatus.mockResolvedValueOnce(unlinkedStatus()).mockResolvedValue(linkedStatus);
    const wrapper = await mountPanel();

    await wrapper.find('[data-testid="blink-username"]').setValue("brian@example.com");
    await wrapper.find('[data-testid="blink-password"] input').setValue("hunter2");
    await wrapper.find('[data-testid="blink-sign-in"]').trigger("click");
    await flushPromises();
    await nextTick();
    await flushPromises();

    const codeInput = document.body.querySelector<HTMLInputElement>('[data-testid="twofa-code"]');
    codeInput!.value = "123456";
    codeInput!.dispatchEvent(new Event("input"));
    await nextTick();

    document.body.querySelector<HTMLElement>('[data-testid="twofa-submit"]')!.click();
    await flushPromises();
    await nextTick();

    expect(mockedVerify).toHaveBeenCalledWith("sess-1", "123456");
    expect(document.body.querySelector('[data-testid="twofa-modal"]')).toBeFalsy();
  });

  it("shows an inline error in the 2FA modal for a rejected code", async () => {
    mockedLink.mockResolvedValue({ status: "verification_required", link_session_id: "sess-1" });
    mockedVerify.mockRejectedValue(new ApiError(400, "That verification code was not accepted."));
    const wrapper = await mountPanel();

    await wrapper.find('[data-testid="blink-username"]').setValue("brian@example.com");
    await wrapper.find('[data-testid="blink-password"] input').setValue("hunter2");
    await wrapper.find('[data-testid="blink-sign-in"]').trigger("click");
    await flushPromises();
    await nextTick();
    await flushPromises();

    document.body.querySelector<HTMLElement>('[data-testid="twofa-submit"]')!.click();
    await flushPromises();
    await nextTick();

    expect(document.body.querySelector('[data-testid="twofa-error"]')?.textContent).toBe(
      "That verification code was not accepted.",
    );
    // still open — the user can retry the code
    expect(document.body.querySelector('[data-testid="twofa-modal"]')).toBeTruthy();
  });

  it("falls back to a generic error in the 2FA modal for a non-API failure", async () => {
    mockedLink.mockResolvedValue({ status: "verification_required", link_session_id: "sess-1" });
    mockedVerify.mockRejectedValue(new TypeError("network down"));
    const wrapper = await mountPanel();

    await wrapper.find('[data-testid="blink-username"]').setValue("brian@example.com");
    await wrapper.find('[data-testid="blink-password"] input').setValue("hunter2");
    await wrapper.find('[data-testid="blink-sign-in"]').trigger("click");
    await flushPromises();
    await nextTick();
    await flushPromises();

    document.body.querySelector<HTMLElement>('[data-testid="twofa-submit"]')!.click();
    await flushPromises();
    await nextTick();

    expect(document.body.querySelector('[data-testid="twofa-error"]')?.textContent).toBe(
      "Could not reach the server.",
    );
  });

  it("closes the 2FA modal when dismissed directly (escape/mask click)", async () => {
    mockedLink.mockResolvedValue({ status: "verification_required", link_session_id: "sess-1" });
    const wrapper = await mountPanel();

    await wrapper.find('[data-testid="blink-username"]').setValue("brian@example.com");
    await wrapper.find('[data-testid="blink-password"] input').setValue("hunter2");
    await wrapper.find('[data-testid="blink-sign-in"]').trigger("click");
    await flushPromises();
    await nextTick();
    await flushPromises();
    expect(document.body.querySelector('[data-testid="twofa-modal"]')).toBeTruthy();

    await wrapper.findAllComponents({ name: "Dialog" })[0]!.vm.$emit("update:visible", false);
    await nextTick();
    await flushPromises();
    expect(document.body.querySelector('[data-testid="twofa-modal"]')).toBeFalsy();
  });
});

describe("BlinkAccountPanel — linked", () => {
  beforeEach(() => {
    mockedStatus.mockResolvedValue(linkedStatus);
  });

  it("shows an info-severity tag for a status other than active or error", async () => {
    mockedStatus.mockResolvedValue({ ...linkedStatus, status: "pending_2fa" });
    const wrapper = await mountPanel();
    expect(wrapper.findComponent({ name: "Tag" }).props("severity")).toBe("info");
  });

  it("shows connection status, camera count, and last sync", async () => {
    const wrapper = await mountPanel();
    const linked = wrapper.find('[data-testid="blink-linked"]');
    expect(linked.text()).toContain("3 camera(s)");
    expect(linked.text()).toContain("Last synced");
  });

  it("omits the last-synced line for an account that hasn't synced yet", async () => {
    mockedStatus.mockResolvedValue({ ...linkedStatus, last_sync: null });
    const wrapper = await mountPanel();
    expect(wrapper.find('[data-testid="blink-linked"]').text()).not.toContain("Last synced");
  });

  it("shows the account error message when status is error", async () => {
    mockedStatus.mockResolvedValue({ ...linkedStatus, status: "error", last_error: "token expired" });
    const wrapper = await mountPanel();
    expect(wrapper.text()).toContain("token expired");
  });

  it("triggers a sync and shows a success toast", async () => {
    mockedSync.mockResolvedValue({ status: "sync_started" });
    const wrapper = await mountPanel();
    await wrapper.find('[data-testid="sync-now"]').trigger("click");
    await flushPromises();
    expect(mockedSync).toHaveBeenCalled();
    expect(toastAdd).toHaveBeenCalledWith(expect.objectContaining({ summary: "Sync started" }));
  });

  it("shows an error toast when sync fails", async () => {
    mockedSync.mockRejectedValue(new ApiError(409, "No Blink account is linked."));
    const wrapper = await mountPanel();
    await wrapper.find('[data-testid="sync-now"]').trigger("click");
    await flushPromises();
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "error", detail: "No Blink account is linked." }),
    );
  });

  it("shows a generic error detail when sync fails with a non-API error", async () => {
    mockedSync.mockRejectedValue(new TypeError("network down"));
    const wrapper = await mountPanel();
    await wrapper.find('[data-testid="sync-now"]').trigger("click");
    await flushPromises();
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "error", detail: "Unexpected error." }),
    );
  });

  it("opens an unlink confirmation and unlinks on confirm", async () => {
    mockedUnlink.mockResolvedValue(undefined);
    mockedStatus.mockResolvedValueOnce(linkedStatus).mockResolvedValue(unlinkedStatus());
    const wrapper = await mountPanel();

    await wrapper.find('[data-testid="open-unlink-confirm"]').trigger("click");
    await nextTick();
    await flushPromises();
    expect(document.body.querySelector('[data-testid="unlink-modal"]')).toBeTruthy();

    document.body.querySelector<HTMLElement>('[data-testid="confirm-unlink"]')!.click();
    await flushPromises();

    expect(mockedUnlink).toHaveBeenCalled();
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ summary: "Blink account unlinked" }),
    );
  });

  it("cancels the unlink confirmation without unlinking", async () => {
    const wrapper = await mountPanel();
    await wrapper.find('[data-testid="open-unlink-confirm"]').trigger("click");
    await nextTick();
    await flushPromises();
    expect(document.body.querySelector('[data-testid="unlink-modal"]')).toBeTruthy();

    const cancelButton = Array.from(document.body.querySelectorAll("button")).find(
      (b) => b.textContent === "Cancel",
    );
    cancelButton!.click();
    await nextTick();
    await flushPromises();

    expect(document.body.querySelector('[data-testid="unlink-modal"]')).toBeFalsy();
    expect(mockedUnlink).not.toHaveBeenCalled();
  });

  it("closes the unlink modal when dismissed directly (escape/mask click)", async () => {
    const wrapper = await mountPanel();
    await wrapper.find('[data-testid="open-unlink-confirm"]').trigger("click");
    await nextTick();
    await flushPromises();
    expect(document.body.querySelector('[data-testid="unlink-modal"]')).toBeTruthy();

    await wrapper.findAllComponents({ name: "Dialog" })[1]!.vm.$emit("update:visible", false);
    await nextTick();
    await flushPromises();
    expect(document.body.querySelector('[data-testid="unlink-modal"]')).toBeFalsy();
  });

  it("shows an error toast when unlink fails", async () => {
    mockedUnlink.mockRejectedValue(new TypeError("network down"));
    const wrapper = await mountPanel();
    await wrapper.find('[data-testid="open-unlink-confirm"]').trigger("click");
    await nextTick();
    await flushPromises();
    document.body.querySelector<HTMLElement>('[data-testid="confirm-unlink"]')!.click();
    await flushPromises();
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "error", summary: "Could not unlink" }),
    );
  });

  it("shows the API error message when unlink fails with an ApiError", async () => {
    mockedUnlink.mockRejectedValue(new ApiError(500, "Server exploded."));
    const wrapper = await mountPanel();
    await wrapper.find('[data-testid="open-unlink-confirm"]').trigger("click");
    await nextTick();
    await flushPromises();
    document.body.querySelector<HTMLElement>('[data-testid="confirm-unlink"]')!.click();
    await flushPromises();
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "error", detail: "Server exploded." }),
    );
  });
});
