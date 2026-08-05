import { expect, seededViewer, storageStatePath, test as setup } from "../fixtures";

// Same idea as auth.setup.ts, for the seeded non-admin account - specs opt
// into it via `test.use({ storageState: storageStatePath("viewer") })`.
setup("authenticate as the seeded viewer", async ({ page }) => {
  await page.goto("/login");
  await page.getByTestId("email").fill(seededViewer.email);
  await page.getByTestId("password").locator("input").fill(seededViewer.password);
  await page.getByTestId("submit").click();
  await expect(page.getByRole("heading", { name: "Library", exact: true })).toBeVisible();
  await page.context().storageState({ path: storageStatePath("viewer") });
});
