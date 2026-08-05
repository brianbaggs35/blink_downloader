import {
  expect,
  openSettingsSection,
  seededCameras,
  seededSyncModule,
  storageStatePath,
  test,
} from "../fixtures";

test.use({ storageState: storageStatePath("admin") });

test.beforeEach(async ({ page }) => {
  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "Settings", exact: true })).toBeVisible();
});

test("General tab: Sync now resolves against the linked Blink account", async ({ page }) => {
  await openSettingsSection(page, "General");
  // The seeded e2e Blink account uses bogus credentials
  // (Settings.disable_blink_network_calls), so this never reaches Blink's
  // real API - it only exercises the request/poll wiring (see
  // stores/blink.ts's syncNow: enqueue, then poll until camera_count > 0,
  // which the seeded cameras already satisfy immediately).
  await expect(page.getByTestId("blink-linked")).toBeVisible();
  await page.getByTestId("sync-now").click();
  await expect(page.getByText("Sync complete")).toBeVisible();
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

  await page.getByTestId("discord-enabled").locator("input").check();
  await page.getByTestId("discord-webhook").fill("https://discord.com/api/webhooks/123/abc");
  await page.getByTestId("save-alerts").click();
  await expect(page.getByText("Alert settings saved")).toBeVisible();

  // The database resets before every test (see ../fixtures' auto-reset
  // fixture), so a reload-based persistence proof is safe here - unlike the
  // old .check()-only idempotency workaround this replaced, a save from an
  // earlier test can never leak into this one.
  await page.reload();
  await openSettingsSection(page, "Alerts");
  await expect(page.getByTestId("discord-enabled").locator("input")).toBeChecked();
});

test("Alerts panel toggles the low-battery alert setting", async ({ page }) => {
  await openSettingsSection(page, "Alerts");
  await expect(page.getByTestId("alerts-form")).toBeVisible();
  await expect(page.getByTestId("alert-on-low-battery").locator("input")).toBeChecked();

  await page.getByTestId("alert-on-low-battery").locator("input").uncheck();
  await page.getByTestId("save-alerts").click();
  await expect(page.getByText("Alert settings saved")).toBeVisible();

  await page.reload();
  await openSettingsSection(page, "Alerts");
  await expect(page.getByTestId("alert-on-low-battery").locator("input")).not.toBeChecked();
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

test("Biometrics panel loads with the model already verified by the stack's own warm-up", async ({
  page,
}) => {
  // Deliberately doesn't click verify-model: that kicks off a real,
  // multi-hundred-MB-if-not-cached model download job, which is expensive
  // enough (see app.testing.seed.warm_up_biometrics_model's own docstring)
  // that this suite pays its cost exactly once, at stack boot, blocking
  // the container healthcheck - not again per-test. This only checks that
  // the panel correctly reflects that already-done work on load.
  await openSettingsSection(page, "Biometrics");
  await expect(page.getByTestId("biometrics-settings-form")).toBeVisible();
  await expect(page.getByTestId("verify-model-success")).toBeVisible();
  await expect(page.getByTestId("biometrics-detected-providers")).toBeVisible();
});
