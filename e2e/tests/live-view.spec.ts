import { expect, seededCameras, storageStatePath, test } from "../fixtures";

test.use({ storageState: storageStatePath("admin") });

test.beforeEach(async ({ page }) => {
  await page.goto("/live");
  await expect(page.getByRole("heading", { name: "Live View", exact: true })).toBeVisible();
  // The first real preview load - wait for it before interacting with
  // anything, since PrimeVue disables Buttons with :loading="true" and the
  // panel starts in a loading state until the <img> fires load/error.
  await expect(page.getByTestId("primary-refresh")).toBeEnabled();
});

test("shows a live preview of the default camera with no error overlay", async ({ page }) => {
  await expect(page.getByTestId("primary-preview")).toBeVisible();
  await expect(page.locator(".preview-overlay")).toHaveCount(0);
});

test("switching the primary camera loads that camera's preview", async ({ page }) => {
  await page.getByTestId("primary-camera-select").click();
  await page.getByRole("option", { name: seededCameras.frontDoor }).click();
  await expect(page.getByTestId("primary-refresh")).toBeEnabled();
  await expect(page.getByTestId("primary-preview")).toBeVisible();
  await expect(page.locator(".preview-overlay")).toHaveCount(0);
});

test("forcing a refresh re-requests the preview without erroring", async ({ page }) => {
  await page.getByTestId("primary-refresh").click();
  await expect(page.getByTestId("primary-refresh")).toBeEnabled();
  await expect(page.locator(".preview-overlay")).toHaveCount(0);
});

test("compare mode adds a second, independently controlled panel", async ({ page }) => {
  await expect(page.getByTestId("secondary-preview")).toHaveCount(0);
  await page.getByTestId("toggle-compare").click();

  // With only two seeded cameras, the secondary panel auto-picks the other one.
  await expect(page.getByTestId("secondary-preview")).toBeVisible();
  await expect(page.getByTestId("secondary-no-camera")).toBeHidden();

  await page.getByTestId("toggle-compare").click();
  await expect(page.getByTestId("secondary-preview")).toHaveCount(0);
});

test("saving a clip surfaces the outcome as a toast", async ({ page }) => {
  // The seeded Blink account is a synthetic fixture, not a live connection,
  // so recording for real always fails here - this exercises the same
  // request/response wiring a successful recording would, just the error path.
  await page.getByTestId("primary-save-clip").click();
  await expect(page.getByText("Could not start recording")).toBeVisible();
});

test("starting a live stream surfaces the outcome inline, without breaking the page", async ({
  page,
}) => {
  // Same synthetic-account caveat as the clip-recording test above -
  // real streaming can't succeed here, so this exercises the request/error
  // wiring rather than an actual video stream.
  await page.getByTestId("primary-live-toggle").click();
  await expect(page.getByTestId("primary-live-error")).toBeVisible();
  await expect(page.getByTestId("primary-preview")).toBeVisible();
});

test("auto-refresh can be toggled on and off", async ({ page }) => {
  const toggle = page.getByTestId("auto-refresh-toggle").locator("input");
  await expect(toggle).not.toBeChecked();
  await toggle.check();
  await expect(toggle).toBeChecked();
  await toggle.uncheck();
  await expect(toggle).not.toBeChecked();
});

test("the Screenshot button downloads a snapshot of the current preview", async ({ page }) => {
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByTestId("primary-screenshot").click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/\.jpg$/);
});

test("the secondary panel supports switching cameras, refreshing, saving a clip, and starting a live stream", async ({
  page,
}) => {
  await page.getByTestId("toggle-compare").click();
  await expect(page.getByTestId("secondary-preview")).toBeVisible();

  await page.getByTestId("secondary-camera-select").click();
  await page.getByRole("option", { name: seededCameras.frontDoor }).click();
  await expect(page.getByTestId("secondary-preview")).toBeVisible();

  await page.getByTestId("secondary-refresh").click();
  await expect(page.getByTestId("secondary-refresh")).toBeEnabled();
  await expect(page.locator(".preview-overlay")).toHaveCount(0);

  await page.getByTestId("secondary-save-clip").click();
  await expect(page.getByText("Could not start recording")).toBeVisible();

  await page.getByTestId("secondary-live-toggle").click();
  await expect(page.getByTestId("secondary-live-error")).toBeVisible();
  await expect(page.getByTestId("secondary-preview")).toBeVisible();
});

test("collapsing the sidebar from Live View's own toggle frees up width", async ({ page }) => {
  await page.getByTestId("live-view-sidebar-toggle").click();
  await expect(page.locator(".sidebar.collapsed")).toBeVisible();
  // Restore for any later test reusing this browser context.
  await page.getByTestId("live-view-sidebar-toggle").click();
  await expect(page.locator(".sidebar.collapsed")).toHaveCount(0);
});
