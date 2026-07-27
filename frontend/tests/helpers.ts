import { createPinia, setActivePinia, type Pinia } from "pinia";
import ConfirmationService from "primevue/confirmationservice";
import PrimeVue from "primevue/config";
import ToastService from "primevue/toastservice";
import { createMemoryHistory, createRouter, type Router } from "vue-router";

import { routes } from "@/router";

import type { BlinkStatusResponse, HealthReport, UserRead } from "@/api";

/** Guard-free router over the real route table. */
export function makeRouter(): Router {
  return createRouter({ history: createMemoryHistory(), routes });
}

export function makePinia(): Pinia {
  const pinia = createPinia();
  setActivePinia(pinia);
  return pinia;
}

export function mountGlobal(pinia: Pinia, router?: Router) {
  return {
    plugins: [pinia, PrimeVue, ToastService, ConfirmationService, ...(router ? [router] : [])],
  };
}

export const fakeUser: UserRead = {
  id: "5f8b1c9e-1111-2222-3333-444455556666",
  email: "admin@example.com",
  is_active: true,
  is_superuser: true,
  is_verified: true,
  display_name: "Brian Baggs",
  timezone: "UTC",
  default_landing_page: "library",
};

export const healthyReport: HealthReport = {
  status: "ok",
  version: "1.0.0",
  database: "ok",
  redis: "ok",
  worker: "ok",
};

/** Unlinked by default - pass overrides for a linked/error/etc. shape. */
export function fakeBlinkStatus(overrides: Partial<BlinkStatusResponse> = {}): BlinkStatusResponse {
  return {
    linked: false,
    status: null,
    last_sync: null,
    last_error: null,
    camera_count: 0,
    network_ids: [],
    total_clip_count: 0,
    daily_clip_counts: [],
    ...overrides,
  };
}

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
