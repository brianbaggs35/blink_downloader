import { createPinia, setActivePinia, type Pinia } from "pinia"
import ConfirmationService from "primevue/confirmationservice"
import PrimeVue from "primevue/config"
import ToastService from "primevue/toastservice"
import Tooltip from "primevue/tooltip"
import {
  createMemoryHistory,
  createRouter,
  type Router,
} from "vue-router"
import type { GlobalMountOptions } from "@vue/test-utils"

import { routes } from "@/router"
import { primeVueOptions } from "@/theme"

import type {
  BlinkStatusResponse,
  CameraRead,
  HealthReport,
  StorageIntegrationSettingsRead,
  UserRead,
} from "@/api"

/** Guard-free router over the real route table. */
export function makeRouter(): Router {
  return createRouter({ history: createMemoryHistory(), routes })
}

export function makePinia(): Pinia {
  const pinia = createPinia()
  setActivePinia(pinia)
  return pinia
}

export function mountGlobal(
  pinia: Pinia,
  router?: Router,
): GlobalMountOptions {
  return {
    plugins: [
      pinia,
      [PrimeVue, primeVueOptions],
      ToastService,
      ConfirmationService,
      ...(router ? [router] : []),
    ],
    directives: { tooltip: Tooltip },
  }
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
}

export const healthyReport: HealthReport = {
  status: "ok",
  version: "1.0.0",
  database: "ok",
  redis: "ok",
  worker: "ok",
}

/** Battery "ok", syncing, no security context by default. */
export function fakeCamera(
  overrides: Partial<CameraRead> = {},
): CameraRead {
  return {
    id: "cccccccc-1111-2222-3333-444455556666",
    name: "Front Door",
    camera_type: "catalina",
    enabled: true,
    battery: "ok",
    last_synced_at: "2026-07-20T12:00:00Z",
    security_context: null,
    ...overrides,
  }
}

/** Unlinked by default - pass overrides for a linked/error/etc. shape. */
export function fakeBlinkStatus(
  overrides: Partial<BlinkStatusResponse> = {},
): BlinkStatusResponse {
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
  }
}

/** All-disconnected by default - pass overrides for a connected/configured shape. */
export function fakeStorageIntegrationSettings(
  overrides: Partial<StorageIntegrationSettingsRead> = {},
): StorageIntegrationSettingsRead {
  return {
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
    auto_archive_backend: "local",
    auto_archive_after_days: 0,
    ...overrides,
  }
}

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}
