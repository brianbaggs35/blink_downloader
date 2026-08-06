import {
  expect,
  openSettingsSection,
  seededAdmin,
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

test("General tab: Sync now polls until the camera count actually catches up", async ({
  page,
}) => {
  await openSettingsSection(page, "General");
  await expect(page.getByTestId("blink-linked")).toBeVisible();

  // The seeded account's cameras already exist, so camera_count > 0 on the
  // very first read and pollUntilReady()'s own retry loop never actually
  // runs - mocked to report 0 for the first couple of reads (the sync
  // click's own immediate check, then one full poll cycle) so that loop
  // genuinely executes at least once before resolving.
  let statusCalls = 0;
  await page.route("**/api/blink/status", (route) => {
    statusCalls += 1;
    const cameraCount = statusCalls <= 2 ? 0 : 2;
    void route.fulfill({
      json: {
        linked: true,
        status: "active",
        last_sync: null,
        last_error: null,
        camera_count: cameraCount,
        network_ids: [],
        total_clip_count: 0,
        daily_clip_counts: [],
      },
    });
  });

  await page.getByTestId("sync-now").click();
  await expect(page.getByText("Sync complete")).toBeVisible({ timeout: 10000 });
  expect(statusCalls).toBeGreaterThanOrEqual(3);
});

test("General tab: password validation rejects a short or mismatched password, then a real change round-trips", async ({
  page,
}) => {
  await openSettingsSection(page, "General");
  const newPassword = page.getByTestId("new-password").locator("input");
  const confirmPassword = page.getByTestId("confirm-password").locator("input");

  await newPassword.fill("short1");
  await confirmPassword.fill("short1");
  await page.getByTestId("save-password").click();
  await expect(page.getByTestId("password-error")).toContainText("at least");

  await newPassword.fill("a-decently-long-password-1");
  await confirmPassword.fill("a-different-password-entirely-2");
  await page.getByTestId("save-password").click();
  await expect(page.getByTestId("password-error")).toContainText("do not match");

  // This is the *seeded admin's real, shared* login used by every other
  // e2e test file's own auth.setup.ts run (including future ones against
  // this same database) - changed and immediately changed back to the
  // known seeded value, wrapped in try/finally so a failed assertion in
  // between can't leave the account permanently changed.
  const temporaryPassword = "temporary-e2e-password-789";
  try {
    await newPassword.fill(temporaryPassword);
    await confirmPassword.fill(temporaryPassword);
    await page.getByTestId("save-password").click();
    await expect(page.getByText("Password updated")).toBeVisible();
  } finally {
    await newPassword.fill(seededAdmin.password);
    await confirmPassword.fill(seededAdmin.password);
    await page.getByTestId("save-password").click();
    await expect(page.getByText("Password updated")).toBeVisible();
  }
});

test("General tab: admin can tune and save Blink sync settings", async ({ page }) => {
  await openSettingsSection(page, "General");
  await page.getByTestId("blink-sync-interval").locator("input").fill("120");
  await page.getByTestId("blink-initial-sync-days").locator("input").fill("7");
  await page.getByTestId("blink-auto-analyze-limit").locator("input").fill("10");
  await page.getByTestId("save-blink-sync").click();
  await expect(page.getByText("Blink sync settings saved")).toBeVisible();

  await page.reload();
  await openSettingsSection(page, "General");
  await expect(page.getByTestId("blink-sync-interval").locator("input")).toHaveValue("120");
  await expect(page.getByTestId("blink-initial-sync-days").locator("input")).toHaveValue("7");
  await expect(page.getByTestId("blink-auto-analyze-limit").locator("input")).toHaveValue("10");
});

test("General tab: a failed password update or Blink sync save surfaces its error inline", async ({
  page,
}) => {
  await openSettingsSection(page, "General");

  // Mocked (unlike the real round-trip test above) so nothing about the
  // seeded admin's actual credentials is ever at risk here.
  await page.route("**/api/users/me", (route) =>
    route.fulfill({ status: 400, json: { detail: "That password is too common." } }),
  );
  await page.getByTestId("new-password").locator("input").fill("a-decently-long-password-1");
  await page.getByTestId("confirm-password").locator("input").fill("a-decently-long-password-1");
  await page.getByTestId("save-password").click();
  await expect(page.getByTestId("password-error")).toContainText("That password is too common.");

  await page.route("**/api/settings/blink-sync", (route) =>
    route.fulfill({ status: 400, json: { detail: "Sync interval must be at least 10 seconds." } }),
  );
  await page.getByTestId("save-blink-sync").click();
  await expect(page.getByTestId("blink-sync-error")).toContainText(
    "Sync interval must be at least 10 seconds.",
  );
});

test("unlinking removes the Blink account, then relinking through a 2FA challenge succeeds", async ({
  page,
}) => {
  await openSettingsSection(page, "General");
  await expect(page.getByTestId("blink-linked")).toBeVisible();

  await page.getByTestId("open-unlink-confirm").click();
  const unlinkDialog = page.getByRole("alertdialog", { name: "Unlink Blink account?" });
  await unlinkDialog.getByRole("button", { name: "Unlink" }).click();
  await expect(page.getByText("Blink account unlinked")).toBeVisible();
  await expect(page.getByTestId("blink-link-form")).toBeVisible();

  // The real link/verify endpoints reach Blink's actual servers - no
  // disable_blink_network_calls gate applies to this flow (BlinkLinker has
  // no test-mode seam) - mocked the same way the onboarding wizard's own
  // copy of this same form does it.
  await page.route("**/api/blink/link", (route) =>
    route.fulfill({ json: { status: "verification_required", link_session_id: "e2e-session" } }),
  );
  await page.getByTestId("blink-username").fill("demo@example.com");
  await page.getByTestId("blink-password").locator("input").fill("hunter2");
  await page.getByTestId("blink-sign-in").click();
  await expect(page.getByTestId("twofa-modal")).toBeVisible();

  await page.route("**/api/blink/verify", (route) => route.fulfill({ json: { status: "linked" } }));
  await page.getByTestId("twofa-code").fill("123456");
  await page.getByTestId("twofa-submit").click();
  await expect(page.getByText("Blink account linked")).toBeVisible();
  await expect(page.getByTestId("twofa-modal")).toBeHidden();
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

test("AI Provider panel: enable, cycle every tier-1 provider, test connection, and save", async ({
  page,
}) => {
  await openSettingsSection(page, "AI Provider");
  await expect(page.getByTestId("ai-provider-form")).toBeVisible();
  await page.getByTestId("ai-enabled").locator("input").check();

  // isCloudProvider/isOllamaProvider's full real matrix (aiProviderCatalog.ts) -
  // base URL shows only for a self-hosted provider, Fetch models only for an
  // Ollama-family one. Cycling every option here is what actually exercises
  // both helpers' full branch set, not just the one provider a save needs.
  const providers: { label: string; baseUrl: boolean; fetchModels: boolean }[] = [
    { label: "OpenAI", baseUrl: false, fetchModels: false },
    { label: "Anthropic", baseUrl: false, fetchModels: false },
    { label: "Ollama Cloud", baseUrl: false, fetchModels: true },
    { label: "Moondream (local)", baseUrl: true, fetchModels: false },
    { label: "Moondream Cloud", baseUrl: false, fetchModels: false },
    { label: "Ollama (local)", baseUrl: true, fetchModels: true },
  ];
  for (const provider of providers) {
    await page.getByTestId("tier1-provider").click();
    await page.getByRole("option", { name: provider.label }).click();
    await expect(page.getByTestId("tier1-base-url")).toHaveCount(provider.baseUrl ? 1 : 0);
    await expect(page.getByTestId("tier1-fetch-models")).toHaveCount(provider.fetchModels ? 1 : 0);
  }
  // Ends on "Ollama (local)" - self-hosted and Ollama-family, so both the
  // base URL field and Fetch models button are visible for what follows.

  // No model yet - runTierTest()'s own early-return validation branch, no
  // network call at all.
  await page.getByTestId("tier1-test").click();
  await expect(page.getByTestId("tier1-test-result")).toContainText(
    "Choose a provider and model first.",
  );
  await page.getByTestId("tier1-test-analysis").click();
  await expect(page.getByTestId("tier1-test-analysis-result")).toContainText(
    "Choose a provider and model first.",
  );

  // A real model, still against the default localhost Ollama URL - nothing
  // listens there in this stack, so both calls fail fast and locally
  // (never a real outbound network call), but exercise the full
  // request/response/error-rendering path for real.
  await page.getByTestId("tier1-model").fill("llava");
  await page.getByTestId("tier1-test").click();
  await expect(page.getByTestId("tier1-test-result")).toContainText("Could not reach Ollama");
  await page.getByTestId("tier1-fetch-models").click();
  await expect(page.getByTestId("tier1-fetch-models-error")).toContainText(
    "Could not list Ollama models",
  );

  // Mock a successful fetch and confirm the model field's suggestions come
  // from that real list (not the static catalog) - filterModelSuggestions()'s
  // fetchedModels branch, otherwise unreachable since no real Ollama server
  // exists in this stack.
  await page.route("**/api/settings/ai/list-models", (route) =>
    route.fulfill({ json: { ok: true, detail: null, models: ["custom-vision-model"] } }),
  );
  await page.getByTestId("tier1-fetch-models").click();
  await expect(page.getByTestId("tier1-fetch-models-error")).toHaveCount(0);
  await page.getByTestId("tier1-model").fill("custom");
  await expect(page.getByRole("option", { name: "custom-vision-model" })).toBeVisible();

  await page.getByTestId("tier1-api-key").locator("input").fill("sk-fake-test-key");
  await page.getByTestId("save-ai-settings").click();
  await expect(page.getByText("AI settings saved")).toBeVisible();

  // The key is now saved server-side - the panel offers to clear it, and a
  // second save with that box checked round-trips resolvedApiKey()'s other
  // branch (clearApiKey, as opposed to a fresh apiKeyInput).
  await expect(page.getByTestId("tier1-clear-key")).toBeVisible();
  await page.getByTestId("tier1-clear-key").locator("input").check();
  await page.getByTestId("save-ai-settings").click();
  await expect(page.getByText("AI settings saved")).toBeVisible();
  await expect(page.getByTestId("tier1-clear-key")).toHaveCount(0);
});

test("AI Provider panel: Tier 2 escalation, linking to Tier 1, and tuning inputs", async ({
  page,
}) => {
  await openSettingsSection(page, "AI Provider");
  await expect(page.getByTestId("ai-provider-form")).toBeVisible();

  // tier2-link-to-tier1 is disabled until tier 1 has a provider.
  await page.getByTestId("tier1-provider").click();
  await page.getByRole("option", { name: "Ollama (local)" }).click();

  await page.getByTestId("tier2-enabled").locator("input").check();
  await expect(page.getByTestId("tier2-link-to-tier1").locator("input")).toBeEnabled();

  await page.getByTestId("tier2-link-to-tier1").locator("input").check();
  await expect(page.getByTestId("tier2-linked-note")).toContainText("Ollama (local)");
  // Linked: tier 2's own provider/key/base-url fields are hidden - it reuses
  // tier 1's.
  await expect(page.getByTestId("tier2-provider")).toHaveCount(0);
  await expect(page.getByTestId("tier2-api-key")).toHaveCount(0);

  await page.getByTestId("tier2-link-to-tier1").locator("input").uncheck();
  await expect(page.getByTestId("tier2-linked-note")).toHaveCount(0);
  await expect(page.getByTestId("tier2-provider")).toBeVisible();

  // A different, self-hosted-but-not-Ollama provider than tier 1 used -
  // Moondream's local default (http://localhost:2020) is also unreachable
  // in this stack, so its test-connection call fails the same safe,
  // fast/local way as tier 1's Ollama one did, just via a different
  // provider's own code path.
  await page.getByTestId("tier2-provider").click();
  // Tier 1's own provider dropdown (already used above) only starts its
  // close (fade-out) transition once this click lands - simultaneous with
  // tier 2's opening (fade-in) one, so for a moment both panels are
  // mid-transition and neither is fully gone. They share the "Moondream
  // (local)" option label, so an immediate getByRole("option", ...) can hit
  // both and fail strict mode. Wait for tier 1's to actually finish leaving.
  await expect(page.locator('[role="listbox"]')).toHaveCount(1);
  await page.getByRole("option", { name: "Moondream (local)" }).click();
  await expect(page.getByTestId("tier2-base-url")).toBeVisible();
  await expect(page.getByTestId("tier2-fetch-models")).toHaveCount(0);

  await page.getByTestId("tier2-test").click();
  await expect(page.getByTestId("tier2-test-result")).toContainText(
    "Choose a provider and model first.",
  );
  await page.getByTestId("tier2-model").fill("moondream2");
  await page.getByTestId("tier2-test").click();
  await expect(page.getByTestId("tier2-test-result")).toContainText("Could not reach Moondream");
  await page.getByTestId("tier2-test-analysis").click();
  // A distinct code path from tier2-test above (MoondreamProvider.analyze(),
  // not test_connection()) with its own error wrapping.
  await expect(page.getByTestId("tier2-test-analysis-result")).toContainText(
    "Moondream request failed",
  );

  await page.getByTestId("tier2-api-key").locator("input").fill("moondream-fake-key");

  await page.getByTestId("keyframes-per-clip").locator("input").fill("6");
  await page.getByTestId("suspicion-threshold").locator("input").fill("0.65");
  await page.getByTestId("feedback-context-count").locator("input").fill("8");

  await page.getByTestId("save-ai-settings").click();
  await expect(page.getByText("AI settings saved")).toBeVisible();

  await page.reload();
  await openSettingsSection(page, "AI Provider");
  await expect(page.getByTestId("keyframes-per-clip").locator("input")).toHaveValue("6");
  await expect(page.getByTestId("suspicion-threshold").locator("input")).toHaveValue("0.65");
  await expect(page.getByTestId("feedback-context-count").locator("input")).toHaveValue("8");
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

test("Alerts panel: configure Slack and SMTP, tune when-to-alert, then clear all saved secrets", async ({
  page,
}) => {
  await openSettingsSection(page, "Alerts");
  await expect(page.getByTestId("alerts-form")).toBeVisible();

  await page.getByTestId("slack-enabled").locator("input").check();
  await page.getByTestId("slack-webhook").fill("https://hooks.slack.com/services/T0/B0/xyz");

  await page.getByTestId("smtp-enabled").locator("input").check();
  await page.getByTestId("smtp-host").fill("smtp.example.com");
  await page.getByTestId("smtp-port").locator("input").fill("2525");
  await page.getByTestId("smtp-username").fill("alerts");
  await page.getByTestId("smtp-password").locator("input").fill("smtp-secret");
  await page.getByTestId("smtp-use-tls").locator("input").uncheck();
  await page.getByTestId("smtp-from-address").fill("alerts@example.com");
  await page.getByTestId("smtp-to-addresses").fill("me@example.com, partner@example.com");

  await page.getByTestId("suspicion-alert-threshold").locator("input").fill("0.65");
  await page.getByTestId("alert-on-proximity").locator("input").uncheck();
  await page.getByTestId("dedup-window").locator("input").fill("30");

  await page.getByTestId("save-alerts").click();
  await expect(page.getByText("Alert settings saved")).toBeVisible();

  await page.reload();
  await openSettingsSection(page, "Alerts");
  await expect(page.getByTestId("slack-enabled").locator("input")).toBeChecked();
  await expect(page.getByTestId("smtp-enabled").locator("input")).toBeChecked();
  await expect(page.getByTestId("smtp-host")).toHaveValue("smtp.example.com");
  await expect(page.getByTestId("smtp-port").locator("input")).toHaveValue("2525");
  await expect(page.getByTestId("smtp-username")).toHaveValue("alerts");
  await expect(page.getByTestId("smtp-use-tls").locator("input")).not.toBeChecked();
  await expect(page.getByTestId("smtp-from-address")).toHaveValue("alerts@example.com");
  await expect(page.getByTestId("smtp-to-addresses")).toHaveValue(
    "me@example.com, partner@example.com",
  );
  await expect(page.getByTestId("suspicion-alert-threshold").locator("input")).toHaveValue(
    "0.65",
  );
  await expect(page.getByTestId("alert-on-proximity").locator("input")).not.toBeChecked();
  await expect(page.getByTestId("dedup-window").locator("input")).toHaveValue("30");

  // Now clear both saved secrets in one save - resolvedSecret()'s "clear"
  // branch for both channels at once (Discord's own clear-webhook path is
  // already covered by the test above this one).
  await page.getByTestId("slack-clear-webhook").locator("input").check();
  await page.getByTestId("smtp-clear-password").locator("input").check();
  await page.getByTestId("save-alerts").click();
  await expect(page.getByText("Alert settings saved")).toBeVisible();
  await expect(page.getByTestId("slack-clear-webhook")).toHaveCount(0);
  await expect(page.getByTestId("smtp-clear-password")).toHaveCount(0);
});

test("Alerts panel: a failed save surfaces the error inline", async ({ page }) => {
  await openSettingsSection(page, "Alerts");
  await expect(page.getByTestId("alerts-form")).toBeVisible();

  await page.route("**/api/alerts/settings", (route) =>
    route.fulfill({ status: 400, json: { detail: "Quiet hours end must be after quiet hours start." } }),
  );
  await page.getByTestId("save-alerts").click();
  await expect(page.getByTestId("alerts-save-error")).toContainText(
    "Quiet hours end must be after quiet hours start.",
  );
});

test("Alerts panel: Send test alert reports a result per enabled channel", async ({ page }) => {
  await openSettingsSection(page, "Alerts");
  await expect(page.getByTestId("alerts-form")).toBeVisible();

  // Nothing enabled yet (seeded default) - a real, unmocked call that
  // legitimately returns no results at all, not a network failure.
  await page.getByTestId("test-alerts").click();
  await expect(page.getByTestId("test-results")).toHaveCount(0);

  // Real Discord/Slack/SMTP delivery can't happen from this environment -
  // mocked the same way IntegrationsView's own connection tests are,
  // exercising testResultRows' full mixed ok/fail rendering.
  await page.route("**/api/alerts/settings/test", (route) =>
    route.fulfill({
      json: {
        discord: { ok: true, detail: "Sent." },
        slack: { ok: false, detail: "Slack returned 404 Not Found." },
        smtp: null,
      },
    }),
  );
  await page.getByTestId("test-alerts").click();
  const results = page.getByTestId("test-results");
  await expect(results).toContainText("Discord:");
  await expect(results).toContainText("Sent.");
  await expect(results).toContainText("Slack:");
  await expect(results).toContainText("Slack returned 404 Not Found.");
  await expect(results.locator(".test-result.ok")).toHaveCount(1);
  await expect(results.locator(".test-result.fail")).toHaveCount(1);
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

test("Security Feed panel: choose cameras, reorder them, tune the grid, and save", async ({
  page,
}) => {
  await openSettingsSection(page, "Security Feed");
  await expect(page.getByTestId("security-feed-settings-form")).toBeVisible();

  // Nothing chosen yet by default - both seeded cameras start in "Not shown".
  // The checkbox and camera-name span are siblings within one .camera-row,
  // so the row (not the checkbox itself) is what hasText needs to filter.
  const frontDoorRow = page.locator(".camera-row", { hasText: seededCameras.frontDoor });
  const backyardRow0 = page.locator(".camera-row", { hasText: seededCameras.backyard });
  await frontDoorRow.locator('[data-testid^="security-feed-camera-"] input').check();
  await backyardRow0.locator('[data-testid^="security-feed-camera-"] input').check();

  // Both now in "Shown, in order" - front door first, backyard second.
  const shownList = page.locator(".camera-order-list").first();
  await expect(shownList).toContainText([seededCameras.frontDoor, seededCameras.backyard].join(""));

  // Move backyard (now index 1) up to the front.
  const backyardRow = shownList.locator(".camera-row", { hasText: seededCameras.backyard });
  await backyardRow.locator('[data-testid^="move-up-"]').click();
  const rows = shownList.locator(".camera-row");
  await expect(rows.first()).toContainText(seededCameras.backyard);
  await expect(rows.last()).toContainText(seededCameras.frontDoor);

  // Then move it back down again - moveDown()'s own swap logic.
  await backyardRow.locator('[data-testid^="move-down-"]').click();
  await expect(rows.first()).toContainText(seededCameras.frontDoor);
  await expect(rows.last()).toContainText(seededCameras.backyard);
  await backyardRow.locator('[data-testid^="move-up-"]').click();

  await page.getByTestId("security-feed-columns").click();
  await page.getByRole("option", { name: "3 columns" }).click();
  await page.getByTestId("security-feed-interval").locator("input").fill("45");

  await page.getByTestId("save-security-feed-settings").click();
  await expect(page.getByText("Security Feed settings saved")).toBeVisible();

  await page.reload();
  await openSettingsSection(page, "Security Feed");
  const reloadedRows = page.locator(".camera-order-list").first().locator(".camera-row");
  await expect(reloadedRows.first()).toContainText(seededCameras.backyard);
  await expect(reloadedRows.last()).toContainText(seededCameras.frontDoor);
  await expect(page.getByTestId("security-feed-columns")).toContainText("3 columns");
  await expect(page.getByTestId("security-feed-interval").locator("input")).toHaveValue("45");

  // Unchecking removes it from "Shown" entirely.
  await page
    .locator(".camera-row", { hasText: seededCameras.frontDoor })
    .locator('[data-testid^="security-feed-camera-"] input')
    .uncheck();
  await expect(page.locator(".camera-order-list").first().locator(".camera-row")).toHaveCount(1);
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

test("Vehicles panel: edit description/length/threshold/enabled, save, then remove vehicle protection", async ({
  page,
}) => {
  await openSettingsSection(page, "Vehicles");
  const card = page.locator('[data-testid^="vehicle-card-"]', {
    hasText: seededCameras.frontDoor,
  });
  await expect(card).toBeVisible();

  // The seeded vehicle already has a 4-point outline (see seed.py), so
  // canSave() is already satisfied without redrawing anything here.
  await card.locator('[data-testid^="vehicle-description-"]').fill(
    "A red pickup truck, usually backed into the driveway.",
  );
  await card.locator('[data-testid^="vehicle-length-"]').locator("input").fill("18");
  await card.locator('[data-testid^="vehicle-threshold-"]').locator("input").fill("4");
  await card.locator('[data-testid^="vehicle-enabled-"]').locator("input").uncheck();

  await card.locator('[data-testid^="save-vehicle-"]').click();
  await expect(
    page.getByText(`Saved vehicle protection for ${seededCameras.frontDoor}`),
  ).toBeVisible();

  await page.reload();
  await openSettingsSection(page, "Vehicles");
  const reloadedCard = page.locator('[data-testid^="vehicle-card-"]', {
    hasText: seededCameras.frontDoor,
  });
  await expect(reloadedCard.locator('[data-testid^="vehicle-description-"]')).toHaveValue(
    "A red pickup truck, usually backed into the driveway.",
  );
  await expect(
    reloadedCard.locator('[data-testid^="vehicle-length-"]').locator("input"),
  ).toHaveValue("18");
  await expect(
    reloadedCard.locator('[data-testid^="vehicle-threshold-"]').locator("input"),
  ).toHaveValue("4");
  await expect(
    reloadedCard.locator('[data-testid^="vehicle-enabled-"]').locator("input"),
  ).not.toBeChecked();

  await reloadedCard.locator('[data-testid^="delete-vehicle-"]').click();
  const dialog = page.getByRole("alertdialog", { name: "Remove vehicle protection" });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Remove" }).click();
  await expect(page.getByText("Vehicle protection removed")).toBeVisible();
  await expect(reloadedCard.locator('[data-testid^="vehicle-description-"]')).toHaveValue("");
  await expect(reloadedCard.locator('[data-testid^="save-vehicle-"]')).toBeDisabled();
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

test("Biometrics panel: toggle, change model/provider/threshold, and save", async ({ page }) => {
  await openSettingsSection(page, "Biometrics");
  await expect(page.getByTestId("biometrics-settings-form")).toBeVisible();

  await page.getByTestId("biometrics-enabled").locator("input").check();

  await page.getByTestId("biometrics-model-pack").click();
  // exact: true - "Fastest (smallest)" is a separate option and would
  // otherwise also match a substring search for "Fast".
  await page.getByRole("option", { name: "Fast", exact: true }).click();

  await page.getByTestId("biometrics-provider-preference").click();
  await page.getByRole("option", { name: "CPU only" }).click();

  await page.getByTestId("biometrics-threshold").locator("input").fill("0.72");

  // Changing model_pack/execution_provider_preference resets
  // model_download_status to "idle" server-side (a previous verification
  // no longer means anything for a different pack/provider) - this is
  // expected, not a bug, and doesn't touch the model files on disk
  // themselves (see app/biometrics/service.py's update_biometrics_settings).
  await page.getByTestId("save-biometrics-settings").click();
  await expect(page.getByText("Biometrics settings saved")).toBeVisible();

  await page.reload();
  await openSettingsSection(page, "Biometrics");
  await expect(page.getByTestId("biometrics-enabled").locator("input")).toBeChecked();
  await expect(page.getByTestId("biometrics-model-pack")).toContainText("Fast");
  await expect(page.getByTestId("biometrics-provider-preference")).toContainText("CPU only");
  await expect(page.getByTestId("biometrics-threshold").locator("input")).toHaveValue("0.72");
});

test("Biometrics panel: re-verifying the model shows the downloading state, then a ready toast", async ({
  page,
}) => {
  await openSettingsSection(page, "Biometrics");
  await expect(page.getByTestId("verify-model-success")).toBeVisible();
  // verify-model is disabled until recognition itself is enabled - model
  // download status is tracked independently of that toggle (the seeded
  // stack warms the model up regardless), but re-triggering it isn't.
  await page.getByTestId("biometrics-enabled").locator("input").check();

  // The model pack is already cached on disk from the stack's own warm-up,
  // so a fresh POST /verify-model still genuinely re-runs the download/load
  // job (see biometrics.py's verify_model_route), it just finishes fast
  // rather than actually fetching anything over the network.
  // Cached-model re-verification can finish in well under a second, so the
  // "downloading" state isn't asserted as its own step here - it can race
  // past before an assertion even gets to look, same as it did in testing.
  await page.getByTestId("verify-model").click();
  await expect(page.getByTestId("verify-model-success")).toBeVisible({ timeout: 20000 });
  await expect(page.getByText("Model ready")).toBeVisible();
});

test("Biometrics panel: a failed model download surfaces the error banner and an error toast", async ({
  page,
}) => {
  await openSettingsSection(page, "Biometrics");
  await expect(page.getByTestId("verify-model-success")).toBeVisible();
  await page.getByTestId("biometrics-enabled").locator("input").check();

  // A real download failure (disk full, corrupt model, ...) isn't something
  // to actually provoke in this environment - mocked the same way other
  // hard-to-reach backend states are mocked elsewhere in this suite.
  await page.route("**/api/biometrics/settings/verify-model", (route) =>
    route.fulfill({
      json: { model_download_status: "downloading", model_download_error: null, model_download_providers: [] },
    }),
  );
  await page.route("**/api/biometrics/settings", (route) =>
    route.fulfill({
      json: {
        model_download_status: "error",
        model_download_error: "Could not download the model pack - disk full.",
        model_download_providers: [],
      },
    }),
  );
  await page.getByTestId("verify-model").click();
  // Unlike the cached, real re-verify above, the mocked "downloading" state
  // here holds for a real POLL_INTERVAL_MS before the mocked error response
  // arrives, so it's reliably observable.
  await expect(page.getByTestId("verify-model-downloading")).toBeVisible();
  await expect(page.getByTestId("verify-model-error")).toBeVisible({ timeout: 20000 });
  await expect(page.getByTestId("verify-model-error")).toContainText("disk full");
  // exact: true - both the error banner and the toast's own detail line
  // also contain this as a substring (the fuller "...disk full." message).
  await expect(page.getByText("Could not download the model", { exact: true })).toBeVisible();
});
