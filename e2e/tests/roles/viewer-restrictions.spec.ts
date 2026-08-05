import {
  expect,
  seededBattery,
  seededCameras,
  seededPerson,
  storageStatePath,
  test,
} from "../../fixtures";

// Real, previously-nonexistent coverage of the non-admin account seeded
// alongside the admin one (see viewer-auth.setup.ts) - every other spec in
// this suite runs as the one seeded admin. Gating happens entirely inside
// view/component templates (auth.isAdmin, derived from is_superuser - see
// stores/auth.ts) rather than via a router guard, so a restriction here is
// only proven by checking the rendered page, not by asserting a redirect.
test.use({ storageState: storageStatePath("viewer") });

test("a viewer can still reach their own pages, including the battery feature", async ({
  page,
}) => {
  // Proves the seeded viewer session is a genuinely working account, not
  // just "everything below is absent" - reuses the battery feature's own
  // seeded fixtures as a real, non-trivial read-path check.
  await page.goto("/status");
  const backyardTile = page.locator('[data-testid^="camera-tile-"]', {
    hasText: seededCameras.backyard,
  });
  await expect(backyardTile.getByText(seededBattery.backyard.status)).toBeVisible();
  await backyardTile.locator('[data-testid^="camera-battery-"]').click();
  await expect(page.getByTestId("battery-history-dialog")).toBeVisible();
});

test("hides admin-only primary nav items and settings sections", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("link", { name: "Connect", exact: true })).toHaveCount(0);

  await page.goto("/settings");
  const children = page.getByTestId("settings-accordion-children");
  await expect(children.getByRole("link", { name: "General", exact: true })).toBeVisible();
  await expect(children.getByRole("link", { name: "About", exact: true })).toBeVisible();
  for (const label of [
    "Users",
    "AI Provider",
    "Biometrics",
    "Cameras",
    "Sync Module",
    "Vehicles",
    "Alerts",
    "Live View",
    "Security Feed",
  ]) {
    await expect(children.getByRole("link", { name: label, exact: true })).toHaveCount(0);
  }
});

test("a direct ?tab= link to an admin-only settings section falls back to General", async ({
  page,
}) => {
  await page.goto("/settings?tab=alerts");
  await expect(page.getByTestId("display-name")).toBeVisible();
  await expect(page.getByTestId("alerts-form")).toHaveCount(0);
});

test("a direct visit to Integrations surfaces a real backend 403, not the link form", async ({
  page,
}) => {
  // No nav link, no router guard - IntegrationsView.vue's own load() call
  // is what actually 403s for a non-admin, proving this is a real backend
  // authorization boundary rather than just a hidden nav item.
  await page.goto("/integrations");
  await expect(page.getByTestId("integrations-load-error")).toBeVisible();
  await expect(page.getByTestId("blink-link-form")).toHaveCount(0);
});

test("General settings shows the linked Blink account but hides admin actions", async ({
  page,
}) => {
  await page.goto("/settings");
  await expect(page.getByTestId("blink-linked")).toBeVisible();
  await expect(page.getByTestId("sync-now")).toHaveCount(0);
  await expect(page.getByTestId("open-unlink-confirm")).toHaveCount(0);
});

test("Library hides selection and bulk actions", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Library", exact: true })).toBeVisible();
  await expect(page.getByTestId("select-all")).toHaveCount(0);
  await expect(page.getByTestId("clip-select")).toHaveCount(0);
});

test("Sync Module shows read-only arm/motion state, no admin controls", async ({ page }) => {
  await page.goto("/sync-module");
  const card = page.getByTestId(/^sync-module-card-/);
  await expect(card).toBeVisible();
  await expect(card.locator('[data-testid^="arm-toggle-"]')).toHaveCount(0);
  await expect(card.locator('[data-testid^="motion-enable-all-"]')).toHaveCount(0);
  await expect(card.locator('[data-testid^="motion-disable-all-"]')).toHaveCount(0);

  const row = card.locator('[data-testid^="camera-motion-row-"]', {
    hasText: seededCameras.frontDoor,
  });
  await expect(row.locator('[data-testid^="camera-motion-"]')).toHaveCount(0);
  await expect(row.getByText(/^Motion (on|off)$/)).toBeVisible();
});

test("Vehicles, AI, and AI Usage hide their settings shortcuts", async ({ page }) => {
  await page.goto("/vehicles");
  await expect(page.getByRole("heading", { name: "Vehicles", exact: true })).toBeVisible();
  await expect(page.getByTestId("go-vehicle-settings")).toHaveCount(0);

  await page.goto("/ai");
  await expect(page.getByRole("heading", { name: "AI", exact: true })).toBeVisible();
  await expect(page.getByTestId("go-ai-settings")).toHaveCount(0);

  await page.goto("/ai-usage");
  await expect(page.getByRole("heading", { name: "AI Usage", exact: true })).toBeVisible();
  await expect(page.getByTestId("go-ai-settings")).toHaveCount(0);
});

test("Security Feed hides customize and per-camera snap/record actions", async ({ page }) => {
  await page.goto("/security-feed");
  await expect(page.getByRole("heading", { name: "Security Feed", exact: true })).toBeVisible();
  await expect(page.getByTestId("customize-feed")).toHaveCount(0);
  await expect(page.locator('[data-testid^="snap-now-"]')).toHaveCount(0);
  await expect(page.locator('[data-testid^="record-now-"]')).toHaveCount(0);
});

test("Live View hides the primary panel's mutation controls", async ({ page }) => {
  await page.goto("/live");
  await expect(page.getByRole("heading", { name: "Live View", exact: true })).toBeVisible();
  await expect(page.getByTestId("primary-live-toggle")).toHaveCount(0);
  await expect(page.getByTestId("primary-refresh")).toHaveCount(0);
  await expect(page.getByTestId("primary-save-clip")).toHaveCount(0);
});

test("Storage hides admin-only actions", async ({ page }) => {
  await page.goto("/storage");
  await expect(page.getByRole("heading", { name: "Storage", exact: true })).toBeVisible();
  await expect(page.getByTestId("auto-archive-card")).toHaveCount(0);
  await expect(page.getByTestId("edit-storage-quota")).toHaveCount(0);
});

test("Biometrics hides a person's admin actions but keeps enrollment usable", async ({
  page,
}) => {
  await page.goto("/biometrics");
  await expect(page.getByRole("heading", { name: "Biometrics", exact: true })).toBeVisible();
  await page.getByText(seededPerson.name).click();
  await expect(page.getByTestId("person-detail-panel")).toBeVisible();

  await expect(page.getByTestId("person-rename-start")).toHaveCount(0);
  await expect(page.getByTestId("delete-person")).toHaveCount(0);
  await expect(page.getByTestId("never-mark-suspicious-toggle")).toHaveCount(0);

  // Enrolling a new face sample isn't admin-gated at all - a viewer can
  // still help keep face recognition up to date.
  await expect(page.getByTestId("enroll-camera-select")).toBeVisible();
});
