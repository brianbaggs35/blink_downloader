import { expect, openSettingsSection, seededCameras, seededSyncModule, test } from "../fixtures";

test.beforeEach(async ({ page }) => {
  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "Settings", exact: true })).toBeVisible();
});

test("Cameras panel toggles a camera and saves its security context", async ({ page }) => {
  await openSettingsSection(page, "Cameras");
  await expect(page.getByTestId("camera-list")).toBeVisible();
  const backyardRow = page.locator('[data-testid^="camera-row-"]', { hasText: seededCameras.backyard });
  await expect(backyardRow).toBeVisible();

  // A timestamp keeps this different from whatever's already saved - the
  // "Save context" link only renders once the field has actually changed
  // from the loaded value, and this suite runs against a persistent
  // database (not reseeded between runs), so a fixed string would go stale
  // the second time this test ever succeeds.
  const contextField = backyardRow.locator('[data-testid^="camera-context-"]');
  await contextField.fill(`Watches the yard and shed. (e2e ${Date.now()})`);
  await backyardRow.locator('[data-testid^="camera-context-save-"]').click();
  await expect(page.getByText("Camera context saved")).toBeVisible();
});

test("Users panel invites a new viewer", async ({ page }) => {
  await openSettingsSection(page, "Users");
  await expect(page.getByTestId("user-list")).toBeVisible();
  await page.getByTestId("open-invite").click();
  await expect(page.getByTestId("invite-modal")).toBeVisible();

  const uniqueEmail = `e2e-viewer-${Date.now()}@example.com`;
  await page.getByTestId("invite-email").fill(uniqueEmail);
  await page.getByTestId("invite-display-name").fill("E2E Viewer");
  await page.getByTestId("invite-password").locator("input").fill("a-strong-password-123");
  await page.getByTestId("submit-invite").click();

  await expect(page.getByTestId("invite-modal")).toBeHidden();
  await expect(page.getByText(uniqueEmail)).toBeVisible();
});

test("AI Provider panel toggles analysis on and picks a tier-1 provider", async ({ page }) => {
  await openSettingsSection(page, "AI Provider");
  await expect(page.getByTestId("ai-provider-form")).toBeVisible();

  await page.getByTestId("tier1-provider").click();
  await page.getByRole("option", { name: "Ollama (local)" }).click();
  await page.getByTestId("save-ai-settings").click();
  await expect(page.getByText("AI settings saved")).toBeVisible();
});

test("Alerts panel enables Discord and saves a webhook URL", async ({ page }) => {
  await openSettingsSection(page, "Alerts");
  await expect(page.getByTestId("alerts-form")).toBeVisible();

  // Persistent database, not reseeded between runs - a prior successful run
  // of this same test may have already left Discord enabled, and .click()
  // would turn an already-checked switch back off. .check() is idempotent
  // (a no-op if already checked), so this reaches "enabled" either way.
  await page.getByTestId("discord-enabled").locator("input").check();
  await page.getByTestId("discord-webhook").fill("https://discord.com/api/webhooks/123/abc");
  await page.getByTestId("save-alerts").click();
  await expect(page.getByText("Alert settings saved")).toBeVisible();
});

test("Sync Module panel shows the seeded identity, read-only", async ({ page }) => {
  await openSettingsSection(page, "Sync Module");
  const row = page.locator('[data-testid^="settings-sync-module-row-"]', {
    hasText: seededSyncModule.name,
  });
  await expect(row).toBeVisible();
  await expect(row).toContainText(seededSyncModule.serial);
  await expect(row).toContainText(seededSyncModule.firmwareVersion);
  await expect(row).toContainText("Enabled");
  await expect(row.locator("button")).toHaveCount(0);
});

test("Vehicles panel lists the seeded cameras to protect", async ({ page }) => {
  await openSettingsSection(page, "Vehicles");
  const frontDoorCard = page.locator('[data-testid^="vehicle-card-"]', {
    hasText: seededCameras.frontDoor,
  });
  await expect(frontDoorCard).toBeVisible();
});

test("Vehicles panel: draw a freeform outline on the reference frame, redraw it, and clear it", async ({
  page,
}) => {
  await openSettingsSection(page, "Vehicles");
  const card = page.locator('[data-testid^="vehicle-card-"]', {
    hasText: seededCameras.frontDoor,
  });
  await expect(card).toBeVisible();

  // Idempotent either-state handling - this suite runs against a
  // persistent, not-reseeded-between-runs database, so a prior run may
  // have already captured a reference frame for this camera. Exactly one
  // of these two buttons renders, never both, never neither - wait for
  // whichever it is to actually settle before the isVisible() check below,
  // rather than racing it immediately after the card itself first appears
  // (isVisible() alone doesn't retry, so a card that's visible-by-text but
  // hasn't finished its own internal render yet reads as neither present).
  const initialCapture = card.locator('[data-testid^="capture-frame-"]');
  const recapture = card.locator('[data-testid^="recapture-frame-"]');
  await expect(initialCapture.or(recapture)).toBeVisible();
  // Which button renders depends on whether a prior, non-reseeded run
  // already captured a frame for this camera, not on anything this test
  // controls.
  // eslint-disable-next-line playwright/no-conditional-in-test
  if (await initialCapture.isVisible()) {
    await initialCapture.click();
  } else {
    await recapture.click();
  }

  const svg = card.locator('[data-testid^="outline-svg-"]');
  await expect(svg).toBeVisible();
  const polygon = svg.locator("polygon");

  // Clear whatever outline a prior run may have left drawn (but not saved).
  const clearButton = card.locator('[data-testid^="clear-points-"]');
  // Same reason as above: whether one's already drawn depends on prior runs.
  // eslint-disable-next-line playwright/no-conditional-in-test
  if (await clearButton.isEnabled()) {
    await clearButton.click();
  }
  // Confirmed empty (not just "clear was clicked") before drawing anything
  // new - a retry of this same test reuses the same server-side vehicle
  // row, and asserting this here (rather than assuming the click above was
  // synchronous and sufficient) is what actually guarantees the draw below
  // starts from a clean slate.
  await expect(polygon).toHaveCount(0);

  // hover({ position }) rather than page.mouse.move(absoluteX, absoluteY):
  // the reference frame can be taller than the viewport, and mouse.move's
  // coordinates are absolute page coordinates with no auto-scroll, so a
  // point past the fold would silently land nowhere. hover() scrolls its
  // target into view first and position is relative to the (post-scroll)
  // element itself - same reasoning as locator.click({ position }) below.
  const box = (await svg.boundingBox())!;
  await svg.hover({ position: { x: box.width * 0.2, y: box.height * 0.2 } });
  await page.mouse.down();
  await svg.hover({ position: { x: box.width * 0.8, y: box.height * 0.2 } });
  await svg.hover({ position: { x: box.width * 0.5, y: box.height * 0.8 } });
  await page.mouse.up();

  await expect(polygon).toHaveCount(1);
  const firstOutline = await polygon.getAttribute("points");

  // Drawing a second stroke replaces the first outline entirely, the same
  // way a lasso tool's next drag replaces its previous selection.
  await svg.hover({ position: { x: box.width * 0.3, y: box.height * 0.3 } });
  await page.mouse.down();
  await svg.hover({ position: { x: box.width * 0.7, y: box.height * 0.7 } });
  await page.mouse.up();
  await expect(polygon).not.toHaveAttribute("points", firstOutline ?? "");

  await clearButton.click();
  await expect(polygon).toHaveCount(0);
});
