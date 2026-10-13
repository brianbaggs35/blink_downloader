import type { Page } from "@playwright/test";

import { expect, storageStatePath, test } from "../../fixtures";

test.use({ storageState: storageStatePath("admin") });

async function openMobileDrawer(page: Page) {
  const toggle = page.getByTestId("mobile-nav-toggle");
  await expect(toggle).toBeVisible();
  await expect(toggle).toBeEnabled();
  // WebKit's iPhone emulation never marks the stationary sticky header as stable.
  await toggle.click({ force: true });

  const drawer = page.getByTestId("mobile-nav-drawer");
  await expect(drawer).toBeVisible();
  return drawer;
}

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Library", exact: true })).toBeVisible();
});

test("the hamburger opens the mobile drawer with the full nav", async ({ page }) => {
  await expect(page.getByTestId("mobile-nav-drawer")).toBeHidden();
  const drawer = await openMobileDrawer(page);
  await expect(drawer).toContainText("Security Feed");
  await expect(drawer).toContainText("Settings");
  await expect(drawer.getByTestId("nav-blink-badge-mobile")).toHaveText("Connected");
});

test("Escape closes the drawer", async ({ page }) => {
  const drawer = await openMobileDrawer(page);
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
});

test("choosing a destination from the drawer navigates and closes it", async ({ page }) => {
  const drawer = await openMobileDrawer(page);
  const statusLink = drawer.getByRole("link", { name: "Status", exact: true });
  await expect(statusLink).toBeVisible();
  await statusLink.click({ force: true });
  await expect(page.getByRole("heading", { name: "Status", exact: true })).toBeVisible();
  await expect(drawer).toBeHidden();
});
