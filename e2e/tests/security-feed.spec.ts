import type { Page } from "@playwright/test";
import { expect, test } from "@playwright/test";

import { seededCameras } from "../fixtures";

test.beforeEach(async ({ page }) => {
  await page.goto("/security-feed");
  await expect(page.getByRole("heading", { name: "Security Feed", exact: true })).toBeVisible();
});

test("shows a tile for every enabled camera, each with a live snapshot", async ({ page }) => {
  await expect(page.getByTestId("feed-grid")).toBeVisible();
  const tiles = page.locator('[data-testid^="feed-tile-"]');
  await expect(tiles).toHaveCount(2);
  await expect(page.getByText(seededCameras.frontDoor)).toBeVisible();
  await expect(page.getByText(seededCameras.backyard)).toBeVisible();
  await expect(page.getByTestId("tile-error")).toHaveCount(0);
});

async function firstTileCameraId(page: Page): Promise<string> {
  const testId = await page.locator('[data-testid^="feed-tile-"]').first().getAttribute("data-testid");
  return testId!.replace("feed-tile-", "");
}

test("Snap forces a fresh capture on that tile without breaking the others", async ({ page }) => {
  const cameraId = await firstTileCameraId(page);
  await page.getByTestId(`snap-now-${cameraId}`).click();
  await expect(page.getByTestId(`snap-now-${cameraId}`)).toBeEnabled();
  await expect(page.getByTestId("tile-error")).toHaveCount(0);
});

test("Record doesn't break the page even though the demo account can't really record", async ({
  page,
}) => {
  // Same synthetic-account caveat as Live View: there's no real camera to
  // trigger a recording on. recordClipNow() deliberately swallows that
  // failure (no user-facing error for this background action), so the only
  // observable outcome is that the button remains usable and nothing crashes.
  const cameraId = await firstTileCameraId(page);
  await page.getByTestId(`record-now-${cameraId}`).click();
  await expect(page.getByTestId(`record-now-${cameraId}`)).toBeEnabled();
});

test("Customize links to the Security Feed settings tab", async ({ page }) => {
  await page.getByTestId("customize-feed").click();
  await expect(page).toHaveURL(/\/settings\?tab=security-feed/);
  await expect(page.getByTestId("security-feed-settings-form")).toBeVisible();
});
