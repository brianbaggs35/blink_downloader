import { expect, test } from "@playwright/test";

import { seededAdmin } from "../fixtures";

// Harness smoke test — proves the seeded stack, TLS proxy, and auth flow work
// end to end. Real product specs live alongside this file.

test("anonymous visitors land on the login screen", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle(/Blink AI Security/);
  await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();
});

test("the seeded admin can sign in and reach the Library", async ({ page }) => {
  await page.goto("/login");
  await page.getByTestId("email").fill(seededAdmin.email);
  await page.getByTestId("password").locator("input").fill(seededAdmin.password);
  await page.getByTestId("submit").click();
  await expect(page.getByRole("heading", { name: "Library", exact: true })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Primary" })).toContainText("Biometrics");
});
