import { expect, seededCameras, seededSyncModule, storageStatePath, test } from "../fixtures";

test.use({ storageState: storageStatePath("admin") });

test.beforeEach(async ({ page }) => {
  await page.goto("/sync-module");
  await expect(page.getByRole("heading", { name: "Sync Module", exact: true })).toBeVisible();
});

test("shows the seeded Sync Module's card instead of the empty state", async ({ page }) => {
  await expect(page.getByTestId("sync-modules-empty")).toBeHidden();
  const card = page.getByTestId(/^sync-module-card-/);
  await expect(card).toBeVisible();
  await expect(card).toContainText(seededSyncModule.name);
  await expect(card).toContainText("Online");
});

test("shows the seeded armed state prominently", async ({ page }) => {
  const card = page.getByTestId(/^sync-module-card-/);
  await expect(card.locator('[data-testid^="arm-state-"]')).toHaveText("Armed");
});

// The seeded e2e stack always runs with BLINK_DISABLE_BLINK_NETWORK_CALLS=true
// (no live Blink account), and each of these guards fires before any DB
// write, so clicking never actually changes the seeded state.
test("disarming surfaces the disabled-network-calls error and leaves state unchanged", async ({
  page,
}) => {
  const card = page.getByTestId(/^sync-module-card-/);
  await card.locator('[data-testid^="arm-toggle-"]').click();
  await expect(page.getByText("Live Blink calls are disabled in this environment.")).toBeVisible();
  await expect(card.locator('[data-testid^="arm-state-"]')).toHaveText("Armed");
});

test("arming and toggling camera motion update the UI immediately when the call succeeds, mocked", async ({
  page,
}) => {
  // Every real arm/motion call is blocked in this stack (see the
  // disabled-network-calls tests above), so replaceSyncModule()/
  // replaceCamera()'s actual "apply the server's response" logic is
  // otherwise unreachable - mocked with the real seeded shape (fetched
  // live, not hand-typed) so the response matches what the app actually
  // expects.
  const syncModules: { id: string; armed: boolean | null }[] = await (
    await page.request.get("/api/sync-modules")
  ).json();
  const syncModule = syncModules[0]!;
  await page.route(`**/api/sync-modules/${syncModule.id}/arm`, (route) =>
    route.fulfill({ json: { ...syncModule, armed: false } }),
  );

  const card = page.getByTestId(/^sync-module-card-/);
  await card.locator('[data-testid^="arm-toggle-"]').click();
  await expect(card.locator('[data-testid^="arm-state-"]')).toHaveText("Disarmed");
  await expect(page.getByText(`${seededSyncModule.name} disarmed`)).toBeVisible();

  const cameras: { camera_id: string; name: string; motion_enabled: boolean }[] = await (
    await page.request.get(`/api/sync-modules/${syncModule.id}/cameras`)
  ).json();
  const camera = cameras.find((c) => c.name === seededCameras.frontDoor)!;
  // Seeded cameras always start motion_enabled: true (Camera.motion_enabled's
  // own column default), so the switch's own optimistic click already
  // assumes "off" - mocking the response back to true here (unchanged)
  // would never be seen as a *change* by Vue, so ToggleSwitch would never
  // resync away from its own optimistic guess. Mock the real "off" outcome
  // the click actually implies instead.
  await page.route(
    `**/api/sync-modules/${syncModule.id}/cameras/${camera.camera_id}/motion`,
    (route) => route.fulfill({ json: { ...camera, motion_enabled: false } }),
  );
  const row = card.locator('[data-testid^="camera-motion-row-"]', {
    hasText: seededCameras.frontDoor,
  });
  await row.getByRole("switch").click();
  await expect(row.getByRole("switch")).not.toBeChecked();
});

test("bulk-enabling motion surfaces the same disabled-network-calls error", async ({ page }) => {
  const card = page.getByTestId(/^sync-module-card-/);
  await card.locator('[data-testid^="motion-enable-all-"]').click();
  await expect(page.getByText("Live Blink calls are disabled in this environment.")).toBeVisible();
});

test("toggling an individual camera's motion detection also fails safely", async ({ page }) => {
  const card = page.getByTestId(/^sync-module-card-/);
  const row = card.locator('[data-testid^="camera-motion-row-"]', {
    hasText: seededCameras.frontDoor,
  });
  await expect(row).toBeVisible();
  await row.getByRole("switch").click();
  await expect(page.getByText("Live Blink calls are disabled in this environment.")).toBeVisible();
});

test("local storage browser lists the seeded items with camera, size, and status", async ({
  page,
}) => {
  const table = page.getByTestId("local-storage-table");
  await expect(table).toBeVisible();
  await expect(table.locator("tbody tr")).toHaveCount(seededSyncModule.localItemCount);
  await expect(table).toContainText(seededCameras.frontDoor);
  await expect(table).toContainText(seededCameras.backyard);
  await expect(table).toContainText("50.0 MB");
  await expect(table).toContainText(seededSyncModule.errorMessage);
});

test("a downloaded item's file link actually serves the clip", async ({ page }) => {
  const table = page.getByTestId("local-storage-table");
  const link = table.locator('[data-testid^="open-item-"]');
  await expect(link).toBeVisible();
  const href = await link.getAttribute("href");
  const response = await page.request.get(href!);
  expect(response.ok()).toBe(true);
  expect(response.headers()["content-type"]).toContain("video/mp4");
});

// The three actions below are worker-task-backed (the click only enqueues a
// job; a background arq worker does the real work), and disable-network-calls
// still blocks every one of them from succeeding - but unlike the arm/motion
// guards above, these fail *inside* the job after it's already been queued,
// so the UI genuinely transitions (queued toast, then an eventual error
// status once the component's own polling catches up) rather than staying
// static. A generous timeout is required to span at least one poll cycle
// (POLL_INTERVAL_MS = 3000 in SyncModuleLocalStorageBrowser.vue).
test("clicking Refresh files is queued, then settles into an error status once the worker runs", async ({
  page,
}) => {
  await page.getByTestId("refresh-local-storage").click();
  await expect(page.getByText("Refreshing files from the Sync Module…")).toBeVisible();
  await expect(page.getByTestId("local-storage-status")).toHaveText("Error", { timeout: 10000 });
  await expect(page.getByTestId("local-storage-status-error")).toContainText(
    "Live Blink calls are disabled in this environment.",
  );
});

test("downloading an available item is queued, then settles into an error status once the worker runs", async ({
  page,
}) => {
  const table = page.getByTestId("local-storage-table");
  const row = table.getByRole("row").filter({ hasText: "50.0 MB" });
  await row.locator('[data-testid^="download-item-"]').click();
  await expect(page.getByText("Queued for download")).toBeVisible();
  await expect(row.locator('[data-testid^="item-status-"]')).toHaveText("Error", {
    timeout: 10000,
  });
  await expect(row).toContainText("Live Blink calls are disabled in this environment.");
  await expect(row.locator('[data-testid^="download-item-"]')).toBeVisible();
});

test("deleting a downloaded item can be cancelled, then confirmed and eventually settles into an error status", async ({
  page,
}) => {
  const table = page.getByTestId("local-storage-table");
  const row = table.getByRole("row").filter({ hasText: seededCameras.backyard });
  await row.locator('[data-testid^="delete-item-"]').click();

  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toContainText("Delete from Sync Module");
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toBeHidden();
  await expect(row.locator('[data-testid^="open-item-"]')).toBeVisible();

  await row.locator('[data-testid^="delete-item-"]').click();
  await dialog.getByRole("button", { name: "Delete" }).click();
  await expect(page.getByText("Queued for deletion")).toBeVisible();
  await expect(row.locator('[data-testid^="item-status-"]')).toHaveText("Error", {
    timeout: 10000,
  });
  await expect(row).toContainText("Live Blink calls are disabled in this environment.");
});
