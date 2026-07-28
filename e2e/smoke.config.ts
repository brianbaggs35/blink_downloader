import { defineConfig, devices } from "@playwright/test";

/**
 * A separate, minimal Playwright project from the main e2e suite
 * (playwright.config.ts) - that one runs against the seeded dev/test stack
 * and never touches the actual production images. This one boots the real
 * production docker-compose stack (see the "Docker · production stack
 * smoke test" job in .github/workflows/ci.yml) against a genuinely empty
 * database and drives the first-run setup wizard, then confirms every nav
 * destination actually renders - the closest thing to "does the shipped
 * image work" this repo has. Deliberately just a handful of load-bearing
 * checks, not a duplicate of the full e2e suite.
 */
export default defineConfig({
  testDir: "./smoke-tests",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never", outputFolder: "smoke-report" }]] : "list",
  use: {
    // Unlike the seeded test stack (docker-compose.test.yml maps host 8443
    // straight through), production maps host 443 -> container 8443 (see
    // BLINK_HTTPS_PORT in docker-compose.yml) - 443 is HTTPS's default port
    // so it's left off here entirely, same as a real browser would.
    baseURL: process.env.SMOKE_BASE_URL ?? "https://localhost",
    ignoreHTTPSErrors: true,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    ...devices["Desktop Chrome"],
  },
});
