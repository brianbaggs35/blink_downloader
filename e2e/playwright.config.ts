import { defineConfig, devices } from "@playwright/test";

/**
 * Runs against the seeded e2e stack (`make e2e`), or any reachable deployment
 * via E2E_BASE_URL. The stack self-signs TLS, hence ignoreHTTPSErrors.
 *
 * workers: 1 (global, not per-project - Playwright's worker pool is shared
 * across every project in one run) is load-bearing, not a perf default left
 * on: every test resets the one shared Postgres database before it runs
 * (see fixtures/index.ts's auto-reset fixture), and TRUNCATE takes an
 * ACCESS EXCLUSIVE lock, which conflicts with *any* concurrent access to
 * the same tables by definition - a second worker's reset (or even a plain
 * read from an unrelated test) mid-truncate doesn't just slow down, it
 * deadlocks. Confirmed empirically: fullyParallel's default worker count
 * produced real `DeadlockDetectedError`s and cascading 500s from
 * /api/testing/reset, failing otherwise-unrelated specs as collateral
 * damage. True per-worker isolation (a separate schema/database per
 * worker) would get parallelism back, but is a materially bigger
 * investment than this suite currently needs.
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
      // Both *.setup.ts files: produce playwright/.auth/admin.json and
      // .../viewer.json respectively. Individual specs load whichever they
      // need via `test.use({ storageState: storageStatePath("...") })`
      // (see fixtures/index.ts) rather than a project-level default, so one
      // project can mix admin/viewer/signed-out specs freely.
      name: "setup",
      testMatch: /.*\.setup\.ts/,
    },
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
      dependencies: ["setup"],
      testIgnore: [/.*\.setup\.ts/, /mobile\//],
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
      dependencies: ["setup"],
      testMatch: /mobile\//,
    },
  ],
});
