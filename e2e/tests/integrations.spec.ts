import { expect, test } from "../fixtures";

test.beforeEach(async ({ page }) => {
  await page.goto("/integrations");
  await expect(page.getByRole("heading", { name: "Integrations", exact: true })).toBeVisible();
});

test("searching narrows the integration cards shown", async ({ page }) => {
  // The cards depend on an API call that resolves after the (immediately
  // rendered, static) heading - wait for one before counting, rather than
  // racing whichever finished loading first.
  await expect(page.getByTestId("integration-card-s3")).toBeVisible();
  const cardsBefore = await page.getByTestId(/^integration-card-/).count();
  expect(cardsBefore).toBeGreaterThanOrEqual(3);

  await page.getByTestId("integrations-search").fill("drive");
  await expect(page.getByTestId("integration-card-google_drive")).toBeVisible();
  await expect(page.getByTestId("integration-card-s3")).toBeHidden();

  await page.getByTestId("integrations-search").fill("");
  await expect(page.getByTestId(/^integration-card-/)).toHaveCount(cardsBefore);
});

test("shows how-to-connect help for a provider", async ({ page }) => {
  await page.getByTestId("integration-help-s3").click();
  await expect(page.getByTestId("help-dialog-s3")).toBeVisible();
  await expect(page.getByTestId("help-dialog-s3")).toContainText("IAM");
});

test("configures and saves S3, and the connection reflects on the Storage page and Library's bulk bar", async ({
  page,
}) => {
  await page.goto("/storage");
  await expect(page.getByRole("heading", { name: "Storage", exact: true })).toBeVisible();
  await expect(page.getByTestId("backend-card-local")).toBeVisible();
  await expect(page.getByTestId("backend-card-s3")).toBeVisible();
  await expect(page.getByTestId("backend-card-google_drive")).toBeVisible();
  await expect(page.getByTestId("backend-card-onedrive")).toBeVisible();
  // Local never needs connecting - no status tag, unlike the cloud backends.
  await expect(page.getByTestId("backend-status-local")).toHaveCount(0);

  await page.goto("/integrations");
  await expect(page.getByRole("heading", { name: "Integrations", exact: true })).toBeVisible();
  await page.getByTestId("integration-configure-s3").click();
  await expect(page.getByTestId("integration-form-s3")).toBeVisible();

  await page.getByTestId("s3-enabled").check();
  await page.getByTestId("s3-bucket").fill("e2e-clips-bucket");
  await page.getByTestId("s3-region").fill("us-east-1");
  await page.getByTestId("s3-access-key").locator("input").fill("AKIAEXAMPLEKEY");
  await page.getByTestId("s3-secret-key").locator("input").fill("supersecretexamplekey");
  await page.getByTestId("integration-save-s3").click();

  await expect(page.getByTestId("integration-status-s3")).toHaveText("Connected");

  await page.goto("/storage");
  await expect(page.getByRole("heading", { name: "Storage", exact: true })).toBeVisible();
  await expect(page.getByTestId("backend-status-s3")).toHaveText("Connected");

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Library", exact: true })).toBeVisible();
  // Archiving needs a clip that's actually downloaded already - the most
  // recent seeded clip can still be "Downloading…" at the moment a test
  // happens to run, so pick one that definitely isn't rather than .first().
  const downloadedCard = page
    .getByTestId("clip-card")
    .filter({ hasNotText: "Downloading…" })
    .first();
  await downloadedCard.getByTestId("clip-select").click();
  await expect(page.getByTestId("bulk-archive")).toBeVisible();
  await expect(page.getByTestId("bulk-archive-destination")).toBeVisible();

  await page.getByTestId("bulk-archive").click();
  await expect(page.getByText(/Queued 1 clip\(s\) to archive/)).toBeVisible();
});
