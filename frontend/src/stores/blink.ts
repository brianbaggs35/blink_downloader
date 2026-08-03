import { defineStore } from "pinia";

import {
  getBlinkStatus,
  linkBlinkAccount,
  triggerBlinkSync,
  unlinkBlinkAccount,
  verifyBlinkAccount,
} from "@/api";
import { pollUntilReady } from "@/lib/pollUntilReady";

import type { BlinkStatusResponse } from "@/api";

interface BlinkState {
  status: BlinkStatusResponse | null;
  loading: boolean;
}

// A freshly-triggered sync runs in a background worker job - camera rows
// may not exist yet the instant it's enqueued. Poll for up to ~9s before
// giving up, rather than reporting a possibly-stale "0 cameras" the moment
// the trigger call itself returns.
const SYNC_DISCOVERY_ATTEMPTS = 6;
const SYNC_DISCOVERY_DELAY_MS = 1500;

export const useBlinkStore = defineStore("blink", {
  state: (): BlinkState => ({
    status: null,
    loading: false,
  }),
  getters: {
    isLinked: (state) => state.status?.linked ?? false,
  },
  actions: {
    async refreshStatus(): Promise<void> {
      this.loading = true;
      try {
        this.status = await getBlinkStatus();
      } finally {
        this.loading = false;
      }
    },
    /** Returns "linked" or "verification_required" (+ a session id to
     * carry into completeLink). */
    async startLink(username: string, password: string) {
      const outcome = await linkBlinkAccount(username, password);
      if (outcome.status === "linked") {
        await this.refreshStatus();
      }
      return outcome;
    },
    async completeLink(linkSessionId: string, code: string): Promise<void> {
      await verifyBlinkAccount(linkSessionId, code);
      await this.refreshStatus();
    },
    async syncNow(): Promise<void> {
      await triggerBlinkSync();
      await pollUntilReady(
        () => this.refreshStatus(),
        () => (this.status?.camera_count ?? 0) > 0,
        SYNC_DISCOVERY_ATTEMPTS,
        SYNC_DISCOVERY_DELAY_MS,
      );
    },
    async unlink(): Promise<void> {
      await unlinkBlinkAccount();
      await this.refreshStatus();
    },
  },
});
