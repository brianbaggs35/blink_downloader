import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { test as base } from "@playwright/test";

import type { Page } from "@playwright/test";

/**
 * Every spec imports `test`/`expect` from here rather than "@playwright/test"
 * directly. Functionally identical unless COVERAGE_DIR is set (only true
 * under `make e2e-coverage`, against a frontend built with
 * VITE_COVERAGE=true - see vite.config.ts): then each test also drains
 * `window.__coverage__` (istanbul's instrumentation counters, injected into
 * the page by vite-plugin-istanbul) to a JSON file nyc can merge and report
 * on afterwards. A plain `make e2e`/`make e2e-test` run against the normal,
 * uninstrumented build has no such global, so this is a no-op there.
 */
export const test = base.extend({
  context: async ({ context }, use, testInfo) => {
    await use(context);
    const coverageDir = process.env.COVERAGE_DIR;
    if (!coverageDir) return;
    for (const [i, page] of context.pages().entries()) {
      const coverage: unknown = await page
        .evaluate(() => (window as unknown as { __coverage__?: unknown }).__coverage__)
        .catch(() => undefined);
      if (!coverage) continue;
      // coverageDir/testId are ours (a Makefile-set env var and Playwright's
      // own generated id), never attacker- or user-controlled input.
      // eslint-disable-next-line security/detect-non-literal-fs-filename
      mkdirSync(coverageDir, { recursive: true });
      // eslint-disable-next-line security/detect-non-literal-fs-filename
      writeFileSync(join(coverageDir, `${testInfo.testId}-${i}.json`), JSON.stringify(coverage));
    }
  },
});

export { expect } from "@playwright/test";

/**
 * Fixture data the e2e stack is seeded with.
 *
 * Seeding happens in the backend container at boot
 * (backend/app/testing/seed.py) and is idempotent. Override the values with
 * BLINK_E2E_ADMIN_EMAIL / BLINK_E2E_ADMIN_PASSWORD on the backend service and
 * mirror them here via environment if you change them.
 */
export const seededAdmin = {
  email: process.env.BLINK_E2E_ADMIN_EMAIL ?? "e2e-admin@example.com",
  password: process.env.BLINK_E2E_ADMIN_PASSWORD ?? "e2e-admin-password-123",
  displayName: "E2E Admin",
};

// Mirrors backend/app/testing/seed.py - keep in sync if the seed changes.
export const seededCameras = {
  frontDoor: "Front Door",
  backyard: "Backyard",
} as const;

export const seededPerson = {
  name: "Alex Demo",
};

/**
 * Settings sections live behind the primary nav's Settings accordion, not a
 * `role="tab"` list - a fresh `page.goto("/settings")` already lands with it
 * expanded (NavLinks.vue expands automatically whenever the route itself is
 * "settings"), but this is defensive against a test that reaches Settings
 * some other way (an in-app link/redirect) instead. Scoped specifically to
 * the accordion's own children container, not the whole nav - several
 * section names (Vehicles, Live View, Security Feed) are shared with a
 * top-level nav destination of the same name, and `getByRole("link")`
 * against the whole nav would otherwise match both.
 */
export async function openSettingsSection(page: Page, name: string): Promise<void> {
  const children = page.getByTestId("settings-accordion-children");
  if (!(await children.isVisible())) {
    await page.getByTestId("settings-accordion-trigger").click();
  }
  await children.getByRole("link", { name, exact: true }).click();
}

export const seededAnalyses = {
  routine: {
    summary: "A package is dropped off at the front door; nothing unusual.",
  },
  suspicious: {
    summary: "A person lingers by the front door for an extended period after dark.",
  },
};

// One vehicle, on the front door camera, with three proximity events.
export const seededVehicle = {
  camera: seededCameras.frontDoor,
  description: "A silver sedan is normally parked in the driveway overnight.",
  proximityEventCount: 3,
};

// One physical, armed, online, local-storage-active Sync Module on the same
// seeded network, with three local (USB) items spanning
// available/downloaded/error - see backend/app/testing/seed.py.
export const seededSyncModule = {
  name: "Home",
  serial: "SN-DEMO-0001",
  firmwareVersion: "2.14.28",
  localItemCount: 3,
  errorMessage: "Failed to prepare this clip from the Sync Module - device busy.",
};
