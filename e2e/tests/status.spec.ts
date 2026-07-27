import { expect, test } from "@playwright/test";

test("shows every health tile as operational for a healthy stack", async ({ page }) => {
  await page.goto("/status");
  await expect(page.getByRole("heading", { name: "Status", exact: true })).toBeVisible();
  for (const tile of ["tile-api", "tile-database", "tile-redis", "tile-worker"]) {
    await expect(page.getByTestId(tile)).toHaveClass(/state-ok/);
  }
});

test("the refresh button re-fetches health", async ({ page }) => {
  await page.goto("/status");
  await page.getByTestId("refresh").click();
  await expect(page.getByTestId("tile-api")).toHaveClass(/state-ok/);
});
