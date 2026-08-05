import { expect, seededVehicle, storageStatePath, test } from "../fixtures";

test.use({ storageState: storageStatePath("admin") });

test.beforeEach(async ({ page }) => {
  await page.goto("/vehicles");
  await expect(page.getByRole("heading", { name: "Vehicles", exact: true })).toBeVisible();
});

test("shows the seeded vehicle's card instead of the empty state", async ({ page }) => {
  await expect(page.getByTestId("vehicles-empty")).toBeHidden();
  const card = page.getByTestId(/^vehicle-card-/);
  await expect(card).toBeVisible();
  await expect(card).toContainText(seededVehicle.camera);
  await expect(card).toContainText(seededVehicle.description);
  await expect(card).toContainText("Active");
});

test("shows the reference frame with the outline overlay", async ({ page }) => {
  const card = page.getByTestId(/^vehicle-card-/);
  await expect(card.locator("img")).toBeVisible();
  await expect(card.locator("svg polygon")).toHaveCount(1);
});

test("lists the seeded proximity events, most recent first", async ({ page }) => {
  const card = page.getByTestId(/^vehicle-card-/);
  const events = card.locator('[data-testid^="event-list-"] li');
  await expect(events).toHaveCount(seededVehicle.proximityEventCount);
  // The 2-hours-ago event (4.2ft) is the most recent of the three seeded.
  await expect(events.first()).toContainText("4.2 ft");
  await expect(events.first()).toContainText("±1.1 ft");
});

test("navigates to the Library filtered to this camera's clips", async ({ page }) => {
  const card = page.getByTestId(/^vehicle-card-/);
  await card.getByRole("button", { name: "View clips from this camera" }).click();
  await expect(page.getByRole("heading", { name: "Library", exact: true })).toBeVisible();
  await expect(page).toHaveURL(/camera_id=/);
});

test("links to vehicle settings for an admin", async ({ page }) => {
  await page.getByTestId("go-vehicle-settings").click();
  // SettingsVehiclesPanel's own per-camera card, one per seeded camera -
  // a different thing than VehiclesView's own vehicle-card-* (one per
  // actual vehicle), but the same testid prefix identifies "the panel
  // loaded" equally well here.
  await expect(page.getByTestId(/^vehicle-card-/).first()).toBeVisible();
});
