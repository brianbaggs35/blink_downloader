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
  const points = card.locator('[data-testid^="outline-point-"]');

  // Clear whatever points a prior run may have left drawn (but not saved).
  const clearButton = card.locator('[data-testid^="clear-points-"]');
  // Same reason: whether points are already drawn depends on prior runs.
  // eslint-disable-next-line playwright/no-conditional-in-test
  if (await clearButton.isEnabled()) {
    await clearButton.click();
  }
  // Confirmed empty (not just "clear was clicked") before drawing anything
  // new - a retry of this same test reuses the same server-side vehicle
  // row, and asserting the count here (rather than assuming the click
  // above was synchronous and sufficient) is what actually guarantees the
  // three clicks below start from zero.
  await expect(points).toHaveCount(0);

  const box = (await svg.boundingBox())!;
  // locator.click({ position }) rather than page.mouse.click(absoluteX,
  // absoluteY): the reference frame can be taller than the viewport, and
  // mouse.click's coordinates are absolute page coordinates with no
  // auto-scroll, so a point past the fold (like the 80%-down third one)
  // silently landed nowhere. locator.click scrolls its target into view
  // first and position is relative to the (post-scroll) element itself.
  await svg.click({ position: { x: box.width * 0.2, y: box.height * 0.2 } });
  await expect(points).toHaveCount(1);
  await svg.click({ position: { x: box.width * 0.8, y: box.height * 0.2 } });
  await expect(points).toHaveCount(2);
  await svg.click({ position: { x: box.width * 0.5, y: box.height * 0.8 } });
  await expect(points).toHaveCount(3);

  const firstPoint = points.first();
  const beforeCx = await firstPoint.getAttribute("cx");
  await firstPoint.hover();
  await page.mouse.down();
  await svg.hover({ position: { x: box.width * 0.35, y: box.height * 0.35 } });
  await page.mouse.up();

  // Dragging repositions the point rather than removing it.
  await expect(points).toHaveCount(3);
  await expect(firstPoint).not.toHaveAttribute("cx", beforeCx ?? "");

  await clearButton.click();
  await expect(points).toHaveCount(0);
});
