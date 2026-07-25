import { defineStore } from "pinia";

import {
  getBlinkStatus,
  linkBlinkAccount,
  triggerBlinkSync,
  unlinkBlinkAccount,
  verifyBlinkAccount,
} from "@/api";

import type { BlinkStatusResponse } from "@/api";

interface BlinkState {
  status: BlinkStatusResponse | null;
  loading: boolean;
}

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
      await this.refreshStatus();
    },
    async unlink(): Promise<void> {
      await unlinkBlinkAccount();
      await this.refreshStatus();
    },
  },
});
