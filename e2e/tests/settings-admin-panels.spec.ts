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

  // The seeded backyard camera has no security context yet (see
  // backend/app/testing/seed.py), so any non-empty value differs from the
  // loaded one - deterministic now that the database resets before every
  // test.
  const contextField = backyardRow.locator('[data-testid^="camera-context-"]');
  await contextField.fill("Watches the yard and shed.");
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

  // The seeded vehicle already has a reference frame and a 4-point outline
  // (see backend/app/testing/seed.py), so this always starts in the
  // "recapture" state with an existing polygon - deterministic now that the
  // database resets before every test. Re-capturing here exercises the real
  // capture flow without disturbing the loaded outline (captureFrame() only
  // bumps the frame image, never touches points).
  const recaptureButton = card.locator('[data-testid^="recapture-frame-"]');
  await recaptureButton.click();
  await expect(recaptureButton).toBeEnabled();
  await expect(card.locator('[data-testid^="vehicle-error-"]')).toHaveCount(0);

  const svg = card.locator('[data-testid^="outline-svg-"]');
  await expect(svg).toBeVisible();
  const polygon = svg.locator("polygon");
  await expect(polygon).toHaveCount(1);

  await card.locator('[data-testid^="clear-points-"]').click();
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

  await card.locator('[data-testid^="clear-points-"]').click();
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
