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

  await page.getByTestId("s3-enabled").locator("input").check();
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
  // Archiving needs a clip that's actually downloaded and won't be yanked
  // out from under it mid-test. The newest clips are seed.py's disposable
  // batch, deliberately reserved for library.spec.ts's own delete/bulk-delete
  // tests to consume concurrently - grabbing .first() here would race those
  // tests over the same clip. .last() (the oldest fixture clip) is never
  // touched by any delete test, so it's stable to archive here regardless of
  // what else is running in parallel.
  const downloadedCard = page
    .getByTestId("clip-card")
    .filter({ hasNotText: "Downloading…" })
    .last();
  await downloadedCard.getByTestId("clip-select").click();
  await expect(page.getByTestId("bulk-archive")).toBeVisible();
  await expect(page.getByTestId("bulk-archive-destination")).toBeVisible();

  await page.getByTestId("bulk-archive").click();
  await expect(page.getByText(/Queued 1 clip\(s\) to archive/)).toBeVisible();
});

test("the Storage page's auto-archive picker only offers connected destinations, and hints to connect one when there are none", async ({
  page,
}) => {
  // Persistent database, not reseeded between runs or test files - the test
  // above saves real-looking S3 credentials as part of its own flow, so
  // this test can't assume nothing is connected without guaranteeing it
  // itself first. Google Drive/OneDrive can't be "connected" via e2e at all
  // (that needs a real OAuth round trip), so S3 is the only one to
  // explicitly reset here.
  await page.goto("/integrations");
  await page.getByTestId("integration-configure-s3").click();
  await page.getByTestId("s3-enabled").locator("input").uncheck();
  await page.getByTestId("integration-save-s3").click();
  await expect(page.getByText("Integration saved")).toBeVisible();

  await page.goto("/storage");
  await expect(page.getByRole("heading", { name: "Storage", exact: true })).toBeVisible();
  await page.getByTestId("edit-auto-archive").click();
  await expect(page.getByTestId("auto-archive-backend")).toBeVisible();

  // The destination picker must not offer an unconnected cloud provider at
  // all (rather than offering it and then warning), so the only option is
  // Local disk.
  await page.getByTestId("auto-archive-backend").click();
  await expect(page.getByRole("option", { name: "Google Drive" })).toHaveCount(0);
  await expect(page.getByRole("option", { name: "Amazon S3" })).toHaveCount(0);
  await expect(page.getByRole("option", { name: "Local disk" })).toBeVisible();
  await page.keyboard.press("Escape");

  await expect(page.getByTestId("storage-no-providers-connected")).toBeVisible();
  await page.getByTestId("storage-go-to-integrations").click();
  await expect(page.getByRole("heading", { name: "Integrations", exact: true })).toBeVisible();
});
