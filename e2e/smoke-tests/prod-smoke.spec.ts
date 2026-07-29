import { expect, test } from "@playwright/test";

// Against a genuinely fresh production stack (empty database, no seed
// script - see docker-compose.yml, which the "Docker · production stack
// smoke test" CI job boots as-is), "/" redirects to "/setup" until the
// first admin account exists (see router/guards.ts).
const ADMIN_EMAIL = `smoke-admin-${Date.now()}@example.com`;
const ADMIN_PASSWORD = "a-strong-smoke-test-password-123";

test("first-run setup (skipping Blink), then every nav destination loads", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/setup$/);

  await page.getByTestId("display-name").fill("Smoke Admin");
  await page.getByTestId("email").fill(ADMIN_EMAIL);
  await page.getByTestId("password").locator("input").fill(ADMIN_PASSWORD);
  await page.getByTestId("confirm").locator("input").fill(ADMIN_PASSWORD);
  await page.getByTestId("submit").click();

  // Step 2 (Storage) - accept the default local directory and move on;
  // SetupView.vue's Stepper is linear, so step 3 never activates (and
  // blink-step-skip never becomes visible) without this click.
  await page.getByTestId("storage-step-continue").click();

  // No real Blink account to link in this ephemeral environment - the
  // wizard must still be completable without one (see SetupView.vue).
  await page.getByTestId("blink-step-skip").click();
  await expect(page.getByTestId("review-no-blink")).toBeVisible();
  await page.getByTestId("finish-setup").click();
  await expect(page.getByRole("heading", { name: "Library", exact: true })).toBeVisible();

  // Same destinations/headings as e2e/tests/nav.spec.ts, driven against the
  // real production image instead of the seeded dev/test stack.
  const destinations: [string, string | RegExp][] = [
    ["Security Feed", "Security Feed"],
    ["Status", "Status"],
    ["Live View", "Live View"],
    ["Storage", "Storage"],
    ["Connect", "Integrations"],
    ["AI", /^AI$/],
    ["AI Usage", "AI Usage"],
    ["Vehicles", "Vehicles"],
    ["Biometrics", "Biometrics"],
  ];
  const nav = page.getByRole("navigation", { name: "Primary" });
  for (const [linkName, heading] of destinations) {
    await nav.getByRole("link", { name: linkName, exact: true }).click();
    await expect(page.getByRole("heading", { name: heading, exact: true }).first()).toBeVisible();
  }

  // Settings is an accordion, not a plain link - expand it, then follow one
  // of its sections in.
  await page.getByTestId("settings-accordion-trigger").click();
  await nav.getByRole("link", { name: "General", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Settings", exact: true })).toBeVisible();
});
