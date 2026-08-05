import { defineConfig, devices } from "@playwright/test";

/**
 * Runs against the seeded e2e stack (`make e2e`), or any reachable deployment
 * via E2E_BASE_URL. The stack self-signs TLS, hence ignoreHTTPSErrors.
 *
 * workers: 1 (global, not per-project - Playwright's worker pool is shared
 * across every project in one run) is load-bearing, not a perf default left
 * on: every test resets the one shared Postgres database before it runs
 * (see fixtures/index.ts's auto-reset fixture, and its resetMode option),
 * and TRUNCATE takes an ACCESS EXCLUSIVE lock, which conflicts with *any*
 * concurrent access to the same tables by definition - a second worker's
 * reset (or even a plain read from an unrelated test) mid-truncate doesn't
 * just slow down, it deadlocks. Confirmed empirically: fullyParallel's
 * default worker count produced real `DeadlockDetectedError`s and cascading
 * 500s from /api/testing/reset, failing otherwise-unrelated specs as
 * collateral damage. True per-worker isolation (a separate schema/database
 * per worker) would get parallelism back, but is a materially bigger
 * investment than this suite currently needs.
 *
 * Project graph runs the onboarding wizard e2e coverage (tests/onboarding/)
 * as part of this same single run, so it counts toward the same coverage
 * report as everything else - not a separate config/stack/CI job:
 *
 *   onboarding-setup (drives /setup on a wiped-empty database, resetMode:
 *   "wipe" - see onboarding.setup.ts)
 *     -> post-onboarding (asserts against that fresh account, resetMode:
 *        "none" so it isn't disturbed - see post-onboarding.spec.ts)
 *        -> identity-setup-admin (auth.setup.ts, resetMode:
 *           "restore-baseline" - wipes the onboarding leftovers and
 *           re-seeds the normal admin/viewer + demo data, then logs in and
 *           saves a *fresh* admin session, since the onboarding wipe
 *           deleted whatever access_token row an earlier admin session
 *           would have pointed at)
 *           -> identity-setup-viewer (viewer-auth.setup.ts, resetMode:
 *              "none" - just logs in as the now-freshly-seeded viewer;
 *              must not reset itself, or it would wipe out the admin
 *              session identity-setup-admin just established)
 *              -> chromium, mobile (everything else, resetMode: "seeded"
 *                 default - domain-only reset before each test, same as
 *                 always)
 *
 * Explicit dependencies rather than relying on file-discovery order:
 * unlike before this graph existed (when both *.setup.ts files just logged
 * in with no reset-mode distinction and their relative order genuinely
 * didn't matter), auth.setup.ts's reset now has to complete before
 * viewer-auth.setup.ts runs, or the viewer login would happen against
 * pre-onboarding-wipe state.
 */
export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "https://localhost:8443",
    ignoreHTTPSErrors: true,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "onboarding-setup",
      testMatch: /onboarding\/onboarding\.setup\.ts$/,
    },
    {
      name: "post-onboarding",
      testMatch: /onboarding\/post-onboarding\.spec\.ts$/,
      dependencies: ["onboarding-setup"],
    },
    {
      // (^|\/)auth\.setup\.ts$ rather than a broader *.setup.ts, so this
      // doesn't also match viewer-auth.setup.ts (its own, later project).
      name: "identity-setup-admin",
      testMatch: /(^|\/)auth\.setup\.ts$/,
      dependencies: ["post-onboarding"],
    },
    {
      name: "identity-setup-viewer",
      testMatch: /viewer-auth\.setup\.ts$/,
      dependencies: ["identity-setup-admin"],
    },
    {
      // Individual specs load whichever saved session they need via
      // `test.use({ storageState: storageStatePath("...") })` (see
      // fixtures/index.ts) rather than a project-level default, so this one
      // project can mix admin/viewer/signed-out specs freely.
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
      dependencies: ["identity-setup-viewer"],
      testIgnore: [/.*\.setup\.ts/, /mobile\//, /onboarding\//],
    },
    {
      // A focused subset (tests/mobile/**) covering the hamburger/drawer and
      // responsive layouts specifically - the rest of the suite already runs
      // desktop-viewport, and re-running every spec at a phone width too
      // would mostly just double the run time for no new signal (the
      // hamburger button itself is CSS-hidden above 768px, so those tests
      // wouldn't even be reachable outside this project).
      name: "mobile",
      use: { ...devices["iPhone 13"] },
      dependencies: ["identity-setup-viewer"],
      testMatch: /mobile\//,
    },
  ],
});
