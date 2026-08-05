import { expect, storageStatePath, test } from "../../fixtures";

test.use({ storageState: storageStatePath("admin") });

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Library", exact: true })).toBeVisible();
});

test("the hamburger opens the mobile drawer with the full nav", async ({ page }) => {
  await expect(page.getByTestId("mobile-nav-drawer")).toBeHidden();
  await page.getByTestId("mobile-nav-toggle").click();
  const drawer = page.getByTestId("mobile-nav-drawer");
  await expect(drawer).toBeVisible();
  await expect(drawer).toContainText("Security Feed");
  await expect(drawer).toContainText("Settings");
  await expect(drawer.getByTestId("nav-blink-badge-mobile")).toHaveText("Connected");
});

test("Escape closes the drawer", async ({ page }) => {
  await page.getByTestId("mobile-nav-toggle").click();
  await expect(page.getByTestId("mobile-nav-drawer")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("mobile-nav-drawer")).toBeHidden();
});

test("choosing a destination from the drawer navigates and closes it", async ({ page }) => {
  await page.getByTestId("mobile-nav-toggle").click();
  const drawer = page.getByTestId("mobile-nav-drawer");
  await drawer.getByRole("link", { name: "Status", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Status", exact: true })).toBeVisible();
  await expect(page.getByTestId("mobile-nav-drawer")).toBeHidden();
});
