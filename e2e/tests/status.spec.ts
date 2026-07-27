import { expect, test } from "../fixtures";

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

test("shows the seeded Blink account as connected, with clip activity", async ({ page }) => {
  await page.goto("/status");
  await expect(page.getByTestId("connection-tag")).toHaveText("Connected");
  await expect(page.getByTestId("connection-card")).toContainText("Last synced");
  await expect(page.getByText("Total clips downloaded")).toBeVisible();
  await expect(page.getByText("Cameras")).toBeVisible();
});

test("links to Settings from the Blink connection card", async ({ page }) => {
  await page.goto("/status");
  await page.getByTestId("manage-blink").click();
  await expect(page).toHaveURL(/\/settings/);
});
