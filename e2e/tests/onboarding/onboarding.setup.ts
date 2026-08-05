import { expect, storageStatePath, test as setup } from "../../fixtures";

// Drives the /setup wizard once. resetMode: "wipe" truncates identity too
// (not just domain data), leaving a genuinely empty database - /setup is a
// one-shot gate reachable only while the users table has zero rows
// (frontend/src/router/guards.ts). This must stay a single, linear journey
// in one test (not split across tests or files): the moment POST /api/setup
// succeeds, that gate closes for the rest of this run, so there's no "start
// over" for a second attempt. post-onboarding.spec.ts (this project's
// dependent) reuses the resulting session via storageStatePath("onboarding")
// instead of re-running this; identity-setup-admin (auth.setup.ts, this
// project's own dependent-of-a-dependent) is what brings the database back
// to the normal seeded baseline afterward - see playwright.config.ts's own
// project-graph comment.
setup.use({ resetMode: "wipe" });

const ADMIN_EMAIL = "onboarding-e2e-admin@example.com";
const ADMIN_PASSWORD = "a-strong-onboarding-password-123";

setup("complete first-run setup, including validation errors, a browsed storage folder, and a failed 2FA attempt", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/setup$/);

  // --- Step 1: Account - validation errors first ---
  await page.getByTestId("display-name").fill("Onboarding E2E Admin");
  await page.getByTestId("email").fill(ADMIN_EMAIL);

  // Too short (MIN_PASSWORD_LENGTH is 12) - a purely client-side check, no
  // network round trip.
  await page.getByTestId("password").locator("input").fill("short1");
  await page.getByTestId("confirm").locator("input").fill("short1");
  await page.getByTestId("submit").click();
  await expect(page.getByTestId("setup-error")).toContainText(
    "Password must be at least 12 characters.",
  );

  // Long enough, but the confirm field doesn't match.
  await page.getByTestId("password").locator("input").fill(ADMIN_PASSWORD);
  await page.getByTestId("confirm").locator("input").fill("a-different-password-123");
  await page.getByTestId("submit").click();
  await expect(page.getByTestId("setup-error")).toContainText("Passwords do not match.");

  // Now valid - this is the real POST /api/setup call.
  await page.getByTestId("confirm").locator("input").fill(ADMIN_PASSWORD);
  await page.getByTestId("submit").click();

  // --- Step 2: Storage - exercise the "Browse" dialog, not just the default path ---
  await expect(page.getByTestId("setup-storage-dir")).toBeVisible();
  await page.getByTestId("setup-storage-browse").click();
  const browser = page.getByTestId("storage-browse-modal");
  await expect(browser).toBeVisible();

  await browser.getByTestId("storage-browse-new-folder-name").fill("onboarding-e2e");
  await browser.getByTestId("storage-browse-create-folder").click();
  // createFolder() navigates into the new folder itself (its response's
  // `path` becomes the dialog's current path) - selecting now confirms that
  // new folder, not the one the dialog opened on.
  await expect(browser.getByTestId("storage-browse-current-path")).toContainText(
    "onboarding-e2e",
  );
  await browser.getByTestId("storage-browse-select").click();
  await expect(browser).toBeHidden();
  await expect(page.getByTestId("setup-storage-dir")).toContainText("onboarding-e2e");

  await page.getByTestId("storage-step-continue").click();

  // --- Step 3: Blink - a mocked 2FA round trip, no real backend/blinkpy call ---
  await page.route("**/api/blink/link", (route) =>
    route.fulfill({
      json: { status: "verification_required", link_session_id: "onboarding-e2e-session" },
    }),
  );
  await page.getByTestId("blink-username").fill("onboarding-e2e@example.com");
  await page.getByTestId("blink-password").locator("input").fill("not-a-real-password");
  await page.getByTestId("blink-sign-in").click();
  await expect(page.getByTestId("twofa-modal")).toBeVisible();

  await page.route("**/api/blink/verify", (route) =>
    route.fulfill({
      status: 400,
      json: { detail: "That verification code was not accepted." },
    }),
  );
  await page.getByTestId("twofa-code").fill("000000");
  await page.getByTestId("twofa-submit").click();
  await expect(page.getByTestId("twofa-error")).toContainText(
    "That verification code was not accepted.",
  );

  // No real Blink account available in this ephemeral environment (same
  // constraint smoke-tests/prod-smoke.spec.ts documents) - close the 2FA
  // dialog and skip linking rather than retry with a code that would also
  // have to be mocked.
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("twofa-modal")).toBeHidden();
  await page.getByTestId("blink-step-skip").click();

  // --- Step 4: Review ---
  await expect(page.getByTestId("review-no-blink")).toBeVisible();
  await page.getByTestId("finish-setup").click();
  await expect(page.getByRole("heading", { name: "Library", exact: true })).toBeVisible();

  await page.context().storageState({ path: storageStatePath("onboarding") });
});
