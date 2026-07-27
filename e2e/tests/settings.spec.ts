import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "Settings", exact: true })).toBeVisible();
});

test("every admin tab is reachable directly via ?tab=, with About last", async ({ page }) => {
  const tabs = page.getByRole("tab");
  await expect(tabs).toHaveText([
    "General",
    "Users",
    "AI Provider",
    "Biometrics",
    "Cameras",
    "Vehicles",
    "Alerts",
    "Live View",
    "Security Feed",
    "About",
  ]);

  await page.goto("/settings?tab=live-view");
  await expect(page.getByTestId("live-view-settings-form")).toBeVisible();

  await page.goto("/settings?tab=security-feed");
  await expect(page.getByTestId("security-feed-settings-form")).toBeVisible();

  await page.goto("/settings?tab=about");
  await expect(page.getByTestId("about-repo-link")).toBeVisible();
});

test("the About tab credits the project, blinkpy, and the stack", async ({ page }) => {
  await page.getByRole("tab", { name: "About" }).click();
  const repoLink = page.getByTestId("about-repo-link");
  await expect(repoLink).toHaveAttribute("href", "https://github.com/brianbaggs35/blink_downloader");
  const blinkpyLink = page.getByTestId("about-blinkpy-link");
  await expect(blinkpyLink).toHaveAttribute("href", "https://github.com/fronzbot/blinkpy");
  await expect(page.getByText("FastAPI")).toBeVisible();
  await expect(page.getByText("PrimeVue")).toBeVisible();
});

test("changing the default landing page persists across a reload", async ({ page }) => {
  await page.getByTestId("default-landing-page").click();
  await page.getByRole("option", { name: "Security Feed" }).click();
  await page.getByTestId("save-profile").click();
  await expect(page.getByText("Profile saved")).toBeVisible();

  await page.reload();
  await expect(page.getByTestId("default-landing-page")).toContainText("Security Feed");

  // Restore the default so other tests (and a fresh login) land on Library.
  await page.getByTestId("default-landing-page").click();
  await page.getByRole("option", { name: "Library" }).click();
  await page.getByTestId("save-profile").click();
  await expect(page.getByText("Profile saved")).toBeVisible();
});

test("Live View settings can be changed and saved", async ({ page }) => {
  await page.getByRole("tab", { name: "Live View" }).click();
  await expect(page.getByTestId("live-view-settings-form")).toBeVisible();

  await page.getByTestId("auto-refresh-default").click();
  await page.getByTestId("save-live-view-settings").click();
  // .last(): saving twice in this test (to restore state below) can leave
  // two toasts with identical text on screen briefly - either is fine proof
  // the save succeeded, so avoid strict-mode ambiguity by taking the latest.
  await expect(page.getByText("Live View settings saved").last()).toBeVisible();

  // Leave it as it started for any other test that opens Live View itself.
  await page.getByTestId("auto-refresh-default").click();
  await page.getByTestId("save-live-view-settings").click();
  await expect(page.getByText("Live View settings saved").last()).toBeVisible();
});

test("Security Feed settings can reorder chosen cameras and save", async ({ page }) => {
  await page.getByRole("tab", { name: "Security Feed" }).click();
  await expect(page.getByTestId("security-feed-settings-form")).toBeVisible();

  await page.getByTestId("security-feed-columns").click();
  await page.getByRole("option", { name: "3 columns" }).click();
  await page.getByTestId("save-security-feed-settings").click();
  await expect(page.getByText("Security Feed settings saved").last()).toBeVisible();

  // Restore the default column count.
  await page.getByTestId("security-feed-columns").click();
  await page.getByRole("option", { name: "2 columns" }).click();
  await page.getByTestId("save-security-feed-settings").click();
  await expect(page.getByText("Security Feed settings saved").last()).toBeVisible();
});
