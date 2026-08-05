import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { test as base } from "@playwright/test";

import type { Page } from "@playwright/test";

/**
 * Every spec imports `test`/`expect` from here rather than "@playwright/test"
 * directly. Two behaviors layered on top of the base test:
 *
 * 1. Resets the backend before every test (an `{ auto: true }` fixture, so
 *    no spec file has to remember to call it) via one of four `resetMode`s
 *    (a test *option*, settable per-file with `test.use({ resetMode: ... })`
 *    the same way `storageState` is):
 *      - "seeded" (default) - POSTs /api/testing/reset: truncates domain
 *        data only (never users/access_tokens) and re-seeds it. This is
 *        what makes it safe for a test to mutate shared state (toggle a
 *        setting, delete a clip, arm/disarm) without leaking into whichever
 *        test runs next.
 *      - "wipe" - POSTs /api/testing/wipe: truncates identity too, leaving
 *        a genuinely empty database. Used only by
 *        tests/onboarding/onboarding.setup.ts, since /setup is a one-shot
 *        gate reachable only while the users table has zero rows.
 *      - "restore-baseline" - POSTs /api/testing/reset-baseline: wipes
 *        everything, then re-seeds identity + domain data (exactly what a
 *        fresh container boot looks like). Used only by auth.setup.ts,
 *        immediately after the onboarding project runs, so every later
 *        test's admin/viewer storage state is backed by a session
 *        established fresh right there rather than one "wipe" just
 *        invalidated.
 *      - "none" - skips the reset entirely. Used by
 *        tests/onboarding/post-onboarding.spec.ts (so its assertions about
 *        the freshly-onboarded account aren't disturbed) and by
 *        viewer-auth.setup.ts (so it doesn't undo what auth.setup.ts's own
 *        "restore-baseline" just established).
 *    All three real endpoints only exist at all when the backend boots with
 *    BLINK_ENABLE_TEST_RESET_ENDPOINT=true (the e2e compose profile; never
 *    prod). Uses Playwright's own `request` fixture (no browser page
 *    needed) with `failOnStatusCode` off so a real reset failure surfaces
 *    as a normal Playwright test error at the point a test's own data
 *    assertions fail, not as an opaque fixture-setup crash.
 * 2. Drains coverage, unchanged from before - see below.
 */
export type ResetMode = "seeded" | "wipe" | "restore-baseline" | "none";

const RESET_MODE_PATHS: Record<Exclude<ResetMode, "none">, string> = {
  seeded: "/api/testing/reset",
  wipe: "/api/testing/wipe",
  "restore-baseline": "/api/testing/reset-baseline",
};

interface Fixtures {
  /** void - nothing reads its value, the reset is the whole point. */
  resetDatabase: void;
}
interface Options {
  resetMode: ResetMode;
}

export const test = base.extend<Fixtures & Options>({
  resetMode: ["seeded", { option: true }],
  resetDatabase: [
    async ({ request, resetMode }, use) => {
      if (resetMode === "none") {
        await use();
        return;
      }
      // eslint-disable-next-line security/detect-object-injection -- resetMode is the narrow ResetMode union (a test option), never untrusted input
      const path = RESET_MODE_PATHS[resetMode];
      const response = await request.post(path, { failOnStatusCode: false });
      if (!response.ok()) {
        throw new Error(
          `POST ${path} returned ${response.status()} - is ` +
            "BLINK_ENABLE_TEST_RESET_ENDPOINT set on the backend service?",
        );
      }
      await use();
    },
    { auto: true },
  ],
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

export const seededViewer = {
  email: process.env.BLINK_E2E_VIEWER_EMAIL ?? "e2e-viewer@example.com",
  password: process.env.BLINK_E2E_VIEWER_PASSWORD ?? "e2e-viewer-password-123",
  displayName: "E2E Viewer",
};

/**
 * A saved storage-state file's path, loaded per spec file via
 * `test.use({ storageState: storageStatePath("admin") })` rather than baked
 * into a project's config - lets a single project mix specs that need
 * different signed-in roles (or none at all) without a project per role.
 * "admin"/"viewer" are produced once by auth.setup.ts/viewer-auth.setup.ts;
 * a genuinely signed-out spec (auth.spec.ts) uses an inline
 * `{ cookies: [], origins: [] }` instead, since there's no file for "no one".
 */
export function storageStatePath(name: string): string {
  return `playwright/.auth/${name}.json`;
}

// Mirrors backend/app/testing/seed.py - keep in sync if the seed changes.
// front_door has a sparse battery history (one "ok" reading); backyard has
// a richer one (an ok -> low transition, currently "low") - deliberately
// different depths so BatteryHistoryDialog e2e coverage sees both shapes.
export const seededCameras = {
  frontDoor: "Front Door",
  backyard: "Backyard",
} as const;

export const seededBattery = {
  frontDoor: { status: "OK", eventCount: 1 },
  backyard: { status: "Low", eventCount: 2 },
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
  // Waits rather than a single isVisible() snapshot: right after a
  // page.reload() on /settings itself, there's a brief window where
  // NavLinks.vue hasn't mounted (and thus auto-expanded) yet - an instant
  // check can catch that window, see "not yet expanded", and click the
  // trigger just as the auto-expand also lands, toggling it back closed and
  // hanging the next line forever. Only clicking the trigger if it's truly
  // never going to expand on its own (a test that reached Settings some
  // other way) avoids that race.
  const alreadyExpanded = await children
    .waitFor({ state: "visible", timeout: 2000 })
    .then(() => true)
    .catch(() => false);
  if (!alreadyExpanded) {
    await page.getByTestId("settings-accordion-trigger").click();
    await children.waitFor({ state: "visible" });
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
