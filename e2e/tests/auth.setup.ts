import { expect, test as setup } from "@playwright/test";

import { seededAdmin } from "../fixtures";

// Runs once before the real specs (see the "setup" project in
// playwright.config.ts) and saves the resulting session cookie so every
// other spec starts already signed in, instead of repeating the login UI
// flow in every file. Specs that need to be signed OUT (login/logout/setup
// redirects) opt back out per-file with `test.use({ storageState: ... })`.
const authFile = "playwright/.auth/admin.json";

setup("authenticate as the seeded admin", async ({ page }) => {
  await page.goto("/login");
  await page.getByTestId("email").fill(seededAdmin.email);
  await page.getByTestId("password").locator("input").fill(seededAdmin.password);
  await page.getByTestId("submit").click();
  await expect(page.getByRole("heading", { name: "Library", exact: true })).toBeVisible();
  await page.context().storageState({ path: authFile });
});
