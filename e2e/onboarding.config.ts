import { defineConfig, devices } from "@playwright/test";

/**
 * A separate stack and config from both the main e2e suite
 * (playwright.config.ts, always-seeded) and the production smoke test
 * (smoke.config.ts, one-shot and throwaway) - /setup is reachable only
 * while the database has zero users (see docker-compose.onboarding.yml's
 * BLINK_SKIP_SEED), and once onboarding.setup.ts completes it, that gate
 * closes for the rest of this stack's lifetime. Splits into a "setup"
 * project (just onboarding.setup.ts, driving the wizard once - including
 * validation errors, the storage directory browser, and a mocked 2FA round
 * trip - and saving the resulting session) and a "post-onboarding" project
 * (everything else here, loading that saved session instead of re-running
 * the wizard).
 */
export default defineConfig({
  testDir: "./onboarding-tests",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI
    ? [["list"], ["html", { open: "never", outputFolder: "onboarding-report" }]]
    : "list",
  use: {
    baseURL: process.env.ONBOARDING_BASE_URL ?? "https://localhost:8444",
    ignoreHTTPSErrors: true,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    ...devices["Desktop Chrome"],
  },
  projects: [
    {
      name: "setup",
      testMatch: /onboarding\.setup\.ts/,
    },
    {
      name: "post-onboarding",
      dependencies: ["setup"],
      testIgnore: /onboarding\.setup\.ts/,
    },
  ],
});
