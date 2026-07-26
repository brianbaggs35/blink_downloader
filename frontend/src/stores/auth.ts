import { defineStore } from "pinia";

import {
  ApiError,
  getMe,
  getSetupStatus,
  login as apiLogin,
  logout as apiLogout,
  runSetup,
} from "@/api";

import type { SetupRequest, UserRead } from "@/api";

interface AuthState {
  user: UserRead | null;
  initialized: boolean | null;
  sessionProbed: boolean;
}

export const useAuthStore = defineStore("auth", {
  state: (): AuthState => ({
    user: null,
    initialized: null,
    sessionProbed: false,
  }),
  getters: {
    isAuthenticated: (state) => state.user !== null,
    isAdmin: (state) => state.user?.is_superuser ?? false,
    displayName: (state) => {
      if (!state.user) {
        return "";
      }
      return state.user.display_name || state.user.email;
    },
    /** Where a fresh login (or the setup wizard) should land, per the
     * user's Settings > General preference. */
    landingRouteName: (state) =>
      state.user?.default_landing_page === "security_feed" ? "security-feed" : "library",
  },
  actions: {
    /** Resolve setup status and (once) probe the session cookie. */
    async bootstrap(): Promise<void> {
      if (this.initialized === null) {
        this.initialized = (await getSetupStatus()).initialized;
      }
      if (this.initialized && !this.sessionProbed) {
        this.sessionProbed = true;
        try {
          this.user = await getMe();
        } catch (error) {
          if (!(error instanceof ApiError) || error.status !== 401) {
            throw error;
          }
        }
      }
    },
    async login(email: string, password: string): Promise<void> {
      await apiLogin(email, password);
      this.user = await getMe();
      this.sessionProbed = true;
    },
    async logout(): Promise<void> {
      await apiLogout();
      this.user = null;
    },
    async completeSetup(payload: SetupRequest): Promise<void> {
      await runSetup(payload);
      this.initialized = true;
      await this.login(payload.email, payload.password);
    },
  },
});
