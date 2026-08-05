import { expect, seededCameras, seededSyncModule, storageStatePath, test } from "../fixtures";

test.use({ storageState: storageStatePath("admin") });

test.beforeEach(async ({ page }) => {
  await page.goto("/sync-module");
  await expect(page.getByRole("heading", { name: "Sync Module", exact: true })).toBeVisible();
});

test("shows the seeded Sync Module's card instead of the empty state", async ({ page }) => {
  await expect(page.getByTestId("sync-modules-empty")).toBeHidden();
  const card = page.getByTestId(/^sync-module-card-/);
  await expect(card).toBeVisible();
  await expect(card).toContainText(seededSyncModule.name);
  await expect(card).toContainText("Online");
});

test("shows the seeded armed state prominently", async ({ page }) => {
  const card = page.getByTestId(/^sync-module-card-/);
  await expect(card.locator('[data-testid^="arm-state-"]')).toHaveText("Armed");
});

// The seeded e2e stack always runs with BLINK_DISABLE_BLINK_NETWORK_CALLS=true
// (no live Blink account), and each of these guards fires before any DB
// write, so clicking never actually changes the seeded state.
test("disarming surfaces the disabled-network-calls error and leaves state unchanged", async ({
  page,
}) => {
  const card = page.getByTestId(/^sync-module-card-/);
  await card.locator('[data-testid^="arm-toggle-"]').click();
  await expect(page.getByText("Live Blink calls are disabled in this environment.")).toBeVisible();
  await expect(card.locator('[data-testid^="arm-state-"]')).toHaveText("Armed");
});

test("bulk-enabling motion surfaces the same disabled-network-calls error", async ({ page }) => {
  const card = page.getByTestId(/^sync-module-card-/);
  await card.locator('[data-testid^="motion-enable-all-"]').click();
  await expect(page.getByText("Live Blink calls are disabled in this environment.")).toBeVisible();
});

test("toggling an individual camera's motion detection also fails safely", async ({ page }) => {
  const card = page.getByTestId(/^sync-module-card-/);
  const row = card.locator('[data-testid^="camera-motion-row-"]', {
    hasText: seededCameras.frontDoor,
  });
  await expect(row).toBeVisible();
  await row.getByRole("switch").click();
  await expect(page.getByText("Live Blink calls are disabled in this environment.")).toBeVisible();
});

test("local storage browser lists the seeded items with camera, size, and status", async ({
  page,
}) => {
  const table = page.getByTestId("local-storage-table");
  await expect(table).toBeVisible();
  await expect(table.locator("tbody tr")).toHaveCount(seededSyncModule.localItemCount);
  await expect(table).toContainText(seededCameras.frontDoor);
  await expect(table).toContainText(seededCameras.backyard);
  await expect(table).toContainText("50.0 MB");
  await expect(table).toContainText(seededSyncModule.errorMessage);
});

test("a downloaded item's file link actually serves the clip", async ({ page }) => {
  const table = page.getByTestId("local-storage-table");
  const link = table.locator('[data-testid^="open-item-"]');
  await expect(link).toBeVisible();
  const href = await link.getAttribute("href");
  const response = await page.request.get(href!);
  expect(response.ok()).toBe(true);
  expect(response.headers()["content-type"]).toContain("video/mp4");
});
