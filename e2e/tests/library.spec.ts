import { expect, seededAnalyses, seededCameras, test } from "../fixtures";

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Library", exact: true })).toBeVisible();
});

test("shows the seeded clips and lets you filter by camera", async ({ page }) => {
  await expect(page.getByTestId("clip-grid")).toBeVisible();
  const cardsBefore = await page.getByTestId("clip-card").count();
  expect(cardsBefore).toBeGreaterThanOrEqual(5);

  await page.getByTestId("camera-filter").click();
  await page.getByRole("option", { name: seededCameras.backyard }).click();
  await expect(page.getByTestId("clear-filters")).toBeVisible();

  const filteredCards = page.getByTestId("clip-card");
  await expect(filteredCards.first()).toBeVisible();
  const count = await filteredCards.count();
  expect(count).toBeGreaterThan(0);
  expect(count).toBeLessThan(cardsBefore);

  await page.getByTestId("clear-filters").click();
  await expect(page.getByTestId("clip-card")).toHaveCount(cardsBefore);
});

test("opens a clip and shows its AI analysis, closing on request", async ({ page }) => {
  // The clip's summary isn't shown on the card itself - open the card that
  // has a recognized-person badge, a reliable anchor for "the suspicious one"
  // (it's the only seeded clip with a recognized face).
  const recognizedCard = page.locator(
    '[data-testid="clip-card"]:has([data-testid="recognized-badge"])',
  );
  await expect(recognizedCard).toHaveCount(1);
  await recognizedCard.click();
  await expect(page.getByTestId("clip-modal")).toBeVisible();
  await expect(page.getByTestId("analysis-body")).toBeVisible();
  await expect(page.getByText(seededAnalyses.suspicious.summary)).toBeVisible();
  await expect(page.getByTestId("recognized-entity-tag").first()).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(page.getByTestId("clip-modal")).toBeHidden();
});

test("selecting clips reveals the bulk action bar", async ({ page }) => {
  await expect(page.getByTestId("bulk-bar")).toBeHidden();
  await page.getByTestId("clip-select").first().click();
  await expect(page.getByTestId("bulk-bar")).toBeVisible();
  await expect(page.getByTestId("bulk-download")).toBeVisible();
  await expect(page.getByTestId("bulk-analyze")).toBeVisible();
  await expect(page.getByTestId("bulk-delete")).toBeVisible();
});
