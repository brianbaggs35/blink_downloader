import type { Locator } from "@playwright/test";

import { expect, test } from "../../fixtures";

async function columnCount(locator: Locator): Promise<number> {
  const value = await locator.evaluate((el) => getComputedStyle(el).gridTemplateColumns);
  return value.trim().split(/\s+/).length;
}

test("Security Feed's grid collapses to a single column on a phone", async ({ page }) => {
  await page.goto("/security-feed");
  const grid = page.getByTestId("feed-grid");
  await expect(grid).toBeVisible();
  expect(await columnCount(grid)).toBe(1);
});

test("Live View's compare mode stacks panels instead of sitting side-by-side", async ({ page }) => {
  await page.goto("/live");
  await expect(page.getByTestId("primary-refresh")).toBeEnabled();
  await page.getByTestId("toggle-compare").click();
  await expect(page.getByTestId("secondary-preview")).toBeVisible();

  const stage = page.locator(".stage.compare");
  expect(await columnCount(stage)).toBe(1);
});

test("the Storage page's backend cards collapse to a single column on a phone", async ({
  page,
}) => {
  await page.goto("/storage");
  const grid = page.getByTestId("backend-grid");
  await expect(grid).toBeVisible();
  expect(await columnCount(grid)).toBe(1);
});

test("the hamburger is the way into navigation - the desktop sidebar is not shown", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByTestId("mobile-nav-toggle")).toBeVisible();
  await expect(page.locator(".sidebar")).toBeHidden();
});
