import { expect, seededAnalyses, seededCameras, seededPerson, test } from "../fixtures";

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Library", exact: true })).toBeVisible();
  // The heading renders synchronously; the clip list is fetched async and
  // arrives later. Several tests below take a plain (non-retrying) .count()
  // reading as their "before" baseline - without this wait, a slow response
  // under heavy parallel load can let that baseline race ahead of the fetch
  // and land on 0, poisoning every count assertion downstream in that test.
  await expect(page.getByTestId("clip-card").first()).toBeVisible();
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
  // Restore is always offered (clips already local are just a no-op on the
  // backend); Archive only once a cloud backend is actually connected - see
  // integrations.spec.ts for that flow end-to-end.
  await expect(page.getByTestId("bulk-restore")).toBeVisible();
  await expect(page.getByTestId("bulk-delete")).toBeVisible();
});

test("bulk-restores the selected clips", async ({ page }) => {
  await page.getByTestId("select-all").click();
  await page.getByTestId("bulk-restore").click();
  await expect(page.getByText(/Queued \d+ clip\(s\) to restore/)).toBeVisible();
  // Restoring clears the selection.
  await expect(page.getByTestId("bulk-bar")).toBeHidden();
});

test("bulk-analyzes the selected clips", async ({ page }) => {
  // Positions 2/3, not 0/1 - the seed's two newest (and only disposable,
  // unrelated-to-anything-else) clips are reserved for the delete tests
  // below, so this doesn't contend with them over the same two clips.
  await page.getByTestId("clip-select").nth(2).click();
  await page.getByTestId("clip-select").nth(3).click();
  await page.getByTestId("bulk-analyze").click();
  await expect(page.getByText(/Queued \d+ clip\(s\) for analysis/)).toBeVisible();
  await expect(page.getByTestId("bulk-bar")).toBeHidden();
});

test("bulk-deletes the selected clips after confirming", async ({ page }) => {
  const before = await page.getByTestId("clip-card").count();
  // Position 1 - the seed's second-newest clip, disposable and unrelated to
  // any analysis/vehicle/face fixture (see seed.py) so removing it here
  // can't break another test elsewhere in the suite. Position 0 (the
  // newest, equally disposable) is reserved for the single-delete test
  // below, so the two tests can't end up racing over the same clip.
  await page.getByTestId("clip-select").nth(1).click();
  await page.getByTestId("bulk-delete").click();

  const dialog = page.getByRole("alertdialog", { name: "Delete clips", exact: true });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("1 clip(s)");
  await dialog.getByRole("button", { name: "Delete" }).click();

  await expect(page.getByText(/Deleted \d+ clip\(s\)/)).toBeVisible();
  await expect(page.getByTestId("clip-card")).toHaveCount(before - 1);
});

test("filters by a recognized person", async ({ page }) => {
  await page.getByTestId("recognized-person-filter").click();
  await page.getByRole("option", { name: seededPerson.name }).click();
  await expect(page.getByTestId("clear-filters")).toBeVisible();
  await expect(page.getByTestId("clip-card")).toHaveCount(1);
  await expect(page.getByTestId("recognized-badge")).toBeVisible();
});

test("the recognized-only toggle and camera filter clear each other appropriately", async ({
  page,
}) => {
  await page.getByTestId("recognized-only-toggle").click();
  await expect(page.getByTestId("clip-card")).toHaveCount(1);

  await page.getByTestId("camera-filter").click();
  await page.getByRole("option", { name: seededCameras.backyard }).click();
  // Backyard has no recognized clips - the two filters combine (AND), not
  // override each other, so this correctly yields zero results. At zero
  // results the grid itself is replaced by an EmptyState (LibraryView.vue),
  // so clip-card's count is the only assertion that applies here.
  await expect(page.getByTestId("clip-card")).toHaveCount(0);

  await page.getByTestId("clear-filters").click();
  await expect(page.getByTestId("clip-card").first()).toBeVisible();
});

test("filters by a date range using the picker's Today shortcut", async ({ page }) => {
  const before = await page.getByTestId("clip-card").count();
  await page.getByTestId("since-filter").locator("input").click();
  await page.getByRole("button", { name: "Today" }).click();
  await expect(page.getByTestId("clear-filters")).toBeVisible();
  // Most of the seed data is hours-to-days old, so "since today" always
  // narrows the list - regardless of how many (if any) of today's own
  // disposable clips other tests have since deleted.
  const count = await page.getByTestId("clip-card").count();
  expect(count).toBeLessThan(before);

  await page.getByTestId("clear-filters").click();
  await expect(page.getByTestId("clip-card")).toHaveCount(before);
});

test("deletes a single clip from its detail view", async ({ page }) => {
  const before = await page.getByTestId("clip-card").count();
  await page.getByTestId("clip-card").first().click();
  await expect(page.getByTestId("clip-modal")).toBeVisible();

  await page.getByTestId("modal-delete").click();
  const dialog = page.getByRole("alertdialog", { name: "Delete clip", exact: true });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Delete" }).click();

  await expect(page.getByText("Clip deleted")).toBeVisible();
  await expect(page.getByTestId("clip-modal")).toBeHidden();
  await expect(page.getByTestId("clip-card")).toHaveCount(before - 1);
});
