import { expect, seededAdmin, storageStatePath, test as setup } from "../fixtures";

// Runs once, after the onboarding project (see playwright.config.ts's own
// project-graph comment) and saves the resulting session cookie so specs
// opt into starting already signed in via
// `test.use({ storageState: storageStatePath("admin") })`, instead of
// repeating the login UI flow in every file. A genuinely signed-out spec
// (auth.spec.ts) uses an inline `{ cookies: [], origins: [] }` instead.
//
// resetMode: "restore-baseline" (rather than the default "seeded") because
// this must also undo onboarding.setup.ts's own "wipe" - that wiped
// identity too, so the normal seeded admin/viewer need a full re-seed, not
// just a domain-data reset, before logging in here can produce a valid
// session at all.
setup.use({ resetMode: "restore-baseline" });

setup("authenticate as the seeded admin", async ({ page }) => {
  await page.goto("/login");
  await page.getByTestId("email").fill(seededAdmin.email);
  await page.getByTestId("password").locator("input").fill(seededAdmin.password);
  await page.getByTestId("submit").click();
  await expect(page.getByRole("heading", { name: "Library", exact: true })).toBeVisible();
  await page.context().storageState({ path: storageStatePath("admin") });
});
