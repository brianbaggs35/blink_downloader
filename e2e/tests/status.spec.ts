import { expect, seededBattery, seededCameras, storageStatePath, test } from "../fixtures";

test.use({ storageState: storageStatePath("admin") });

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
  // Scoped to the stat tile specifically - the new "Cameras" section heading
  // below is also just the word "Cameras", and a plain getByText("Cameras")
  // now matches both.
  await expect(page.locator(".stat-tile", { hasText: "Cameras" })).toBeVisible();
});

test("links to Settings from the Blink connection card", async ({ page }) => {
  await page.goto("/status");
  await page.getByTestId("manage-blink").click();
  await expect(page).toHaveURL(/\/settings/);
});

test("shows the seeded cameras' battery status", async ({ page }) => {
  await page.goto("/status");
  const frontDoorTile = page.locator('[data-testid^="camera-tile-"]', {
    hasText: seededCameras.frontDoor,
  });
  await expect(frontDoorTile.getByText(seededBattery.frontDoor.status)).toBeVisible();

  const backyardTile = page.locator('[data-testid^="camera-tile-"]', {
    hasText: seededCameras.backyard,
  });
  await expect(backyardTile.getByText(seededBattery.backyard.status)).toBeVisible();
});

test("opens a camera's battery history on click", async ({ page }) => {
  await page.goto("/status");
  const backyardTile = page.locator('[data-testid^="camera-tile-"]', {
    hasText: seededCameras.backyard,
  });
  await backyardTile.locator('[data-testid^="camera-battery-"]').click();

  const dialog = page.getByTestId("battery-history-dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText(seededCameras.backyard);
  await expect(page.getByTestId("battery-timeline")).toBeVisible();
  await expect(page.getByTestId("battery-activity-list").locator("li")).toHaveCount(
    seededBattery.backyard.eventCount,
  );
});
