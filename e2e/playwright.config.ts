import { defineConfig, devices } from "@playwright/test";

/**
 * Runs against the seeded e2e stack (`make e2e`), or any reachable deployment
 * via E2E_BASE_URL. The stack self-signs TLS, hence ignoreHTTPSErrors.
 */
export default defineConfig({
  testDir: "./tests",
  fullyParallel: true,
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
      name: "setup",
      testMatch: /auth\.setup\.ts/,
    },
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], storageState: "playwright/.auth/admin.json" },
      dependencies: ["setup"],
      testIgnore: [/auth\.setup\.ts/, /mobile\//],
    },
    {
      // A focused subset (tests/mobile/**) covering the hamburger/drawer and
      // responsive layouts specifically - the rest of the suite already runs
      // desktop-viewport, and re-running every spec at a phone width too
      // would mostly just double the run time for no new signal (the
      // hamburger button itself is CSS-hidden above 768px, so those tests
      // wouldn't even be reachable outside this project).
      name: "mobile",
      use: { ...devices["iPhone 13"], storageState: "playwright/.auth/admin.json" },
      dependencies: ["setup"],
      testMatch: /mobile\//,
    },
  ],
});
