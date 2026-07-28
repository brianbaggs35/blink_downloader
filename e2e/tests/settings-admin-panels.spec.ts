import { expect, seededCameras, test } from "../fixtures";

test.beforeEach(async ({ page }) => {
  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "Settings", exact: true })).toBeVisible();
});

test("Cameras panel toggles a camera and saves its security context", async ({ page }) => {
  await page.getByRole("tab", { name: "Cameras" }).click();
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
  await page.getByRole("tab", { name: "Users" }).click();
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
  await page.getByRole("tab", { name: "AI Provider" }).click();
  await expect(page.getByTestId("ai-provider-form")).toBeVisible();

  await page.getByTestId("tier1-provider").click();
  await page.getByRole("option", { name: "Ollama (local)" }).click();
  await page.getByTestId("save-ai-settings").click();
  await expect(page.getByText("AI settings saved")).toBeVisible();
});

test("Alerts panel enables Discord and saves a webhook URL", async ({ page }) => {
  await page.getByRole("tab", { name: "Alerts" }).click();
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

test("Archived panel warns when the selected destination isn't connected yet, and links to Integrations", async ({
  page,
}) => {
  await page.getByRole("tab", { name: "Archived" }).click();
  await expect(page.getByTestId("auto-archive-backend")).toBeVisible();

  await page.getByTestId("auto-archive-backend").click();
  await page.getByRole("option", { name: "Google Drive" }).click();
  await expect(page.getByTestId("archived-not-ready-warning")).toBeVisible();

  await page.getByTestId("archived-go-to-integrations").click();
  await expect(page.getByRole("heading", { name: "Integrations", exact: true })).toBeVisible();
});

test("Vehicles panel lists the seeded cameras to protect", async ({ page }) => {
  await page.getByRole("tab", { name: "Vehicles" }).click();
  const frontDoorCard = page.locator('[data-testid^="vehicle-card-"]', {
    hasText: seededCameras.frontDoor,
  });
  await expect(frontDoorCard).toBeVisible();
});

test("Vehicles panel: draw, drag, and clear an outline on the reference frame", async ({
  page,
}) => {
  await page.getByRole("tab", { name: "Vehicles" }).click();
  const card = page.locator('[data-testid^="vehicle-card-"]', {
    hasText: seededCameras.frontDoor,
  });
  await expect(card).toBeVisible();

  // Idempotent either-state handling - this suite runs against a
  // persistent, not-reseeded-between-runs database, so a prior run may
  // have already captured a reference frame for this camera.
  const initialCapture = card.locator('[data-testid^="capture-frame-"]');
  // Which button renders depends on whether a prior, non-reseeded run
  // already captured a frame for this camera, not on anything this test
  // controls.
  // eslint-disable-next-line playwright/no-conditional-in-test
  if (await initialCapture.isVisible().catch(() => false)) {
    await initialCapture.click();
  } else {
    await card.locator('[data-testid^="recapture-frame-"]').click();
  }

  const svg = card.locator('[data-testid^="outline-svg-"]');
  await expect(svg).toBeVisible();

  // Clear whatever points a prior run may have left drawn (but not saved).
  const clearButton = card.locator('[data-testid^="clear-points-"]');
  // Same reason: whether points are already drawn depends on prior runs.
  // eslint-disable-next-line playwright/no-conditional-in-test
  if (await clearButton.isEnabled()) {
    await clearButton.click();
  }

  const box = (await svg.boundingBox())!;
  await page.mouse.click(box.x + box.width * 0.2, box.y + box.height * 0.2);
  await page.mouse.click(box.x + box.width * 0.8, box.y + box.height * 0.2);
  await page.mouse.click(box.x + box.width * 0.5, box.y + box.height * 0.8);

  const points = card.locator('[data-testid^="outline-point-"]');
  await expect(points).toHaveCount(3);

  const firstPoint = points.first();
  const beforeCx = await firstPoint.getAttribute("cx");
  await firstPoint.hover();
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.35, box.y + box.height * 0.35, { steps: 5 });
  await page.mouse.up();

  // Dragging repositions the point rather than removing it.
  await expect(points).toHaveCount(3);
  await expect(firstPoint).not.toHaveAttribute("cx", beforeCx ?? "");

  await clearButton.click();
  await expect(points).toHaveCount(0);
});
