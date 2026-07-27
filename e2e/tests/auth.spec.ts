import { expect, test } from "@playwright/test";

import { seededAdmin } from "../fixtures";

// The chromium project starts every spec already signed in (see
// playwright.config.ts + auth.setup.ts) - these tests are specifically
// about the signed-out experience, so they opt back out of that.
test.use({ storageState: { cookies: [], origins: [] } });

test("anonymous visitors land on the login screen", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle(/Blink AI Security/);
  await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();
});

test("an unknown route while signed out also redirects to login", async ({ page }) => {
  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();
});

test("wrong credentials show an inline error and don't navigate away", async ({ page }) => {
  await page.goto("/login");
  await page.getByTestId("email").fill(seededAdmin.email);
  await page.getByTestId("password").locator("input").fill("definitely-wrong-password");
  await page.getByTestId("submit").click();
  await expect(page.getByTestId("login-error")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();
});

test("the seeded admin can sign in and reach the Library, with the full nav visible", async ({
  page,
}) => {
  await page.goto("/login");
  await page.getByTestId("email").fill(seededAdmin.email);
  await page.getByTestId("password").locator("input").fill(seededAdmin.password);
  await page.getByTestId("submit").click();
  await expect(page.getByRole("heading", { name: "Library", exact: true })).toBeVisible();
  const nav = page.getByRole("navigation", { name: "Primary" });
  await expect(nav).toContainText("Security Feed");
  await expect(nav).toContainText("Live View");
  await expect(nav).toContainText("Biometrics");
  await expect(nav).toContainText("Settings");
});

test("signing out returns to the login screen", async ({ page }) => {
  await page.goto("/login");
  await page.getByTestId("email").fill(seededAdmin.email);
  await page.getByTestId("password").locator("input").fill(seededAdmin.password);
  await page.getByTestId("submit").click();
  await expect(page.getByRole("heading", { name: "Library", exact: true })).toBeVisible();

  await page.getByTestId("sign-out").click();
  await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();

  // The session cookie is really gone, not just a client-side route change.
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();
});
