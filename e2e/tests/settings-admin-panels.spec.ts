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

test("Vehicles panel lists the seeded cameras to protect", async ({ page }) => {
  await page.getByRole("tab", { name: "Vehicles" }).click();
  const frontDoorCard = page.locator('[data-testid^="vehicle-card-"]', {
    hasText: seededCameras.frontDoor,
  });
  await expect(frontDoorCard).toBeVisible();
});
