import { expect, test } from "../fixtures";

test.beforeEach(async ({ page }) => {
  await page.goto("/");
});

test("every primary nav destination actually navigates there", async ({ page }) => {
  const destinations: [string, string | RegExp][] = [
    ["Security Feed", "Security Feed"],
    ["Status", "Status"],
    ["Live View", "Live View"],
    ["Storage", "Storage"],
    ["AI", /^AI$/],
    ["AI Usage", "AI Usage"],
    ["Vehicles", "Vehicles"],
    ["Biometrics", "Biometrics"],
    ["Settings", "Settings"],
  ];
  const nav = page.getByRole("navigation", { name: "Primary" });
  for (const [linkName, heading] of destinations) {
    await nav.getByRole("link", { name: linkName, exact: true }).click();
    await expect(page.getByRole("heading", { name: heading, exact: true }).first()).toBeVisible();
  }
  await nav.getByRole("link", { name: "Library", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Library", exact: true })).toBeVisible();
});

test("collapsing the sidebar persists across a reload", async ({ page }) => {
  const toggle = page.getByTestId("sidebar-collapse-toggle");
  await toggle.click();
  await expect(page.locator(".sidebar.collapsed")).toBeVisible();

  await page.reload();
  await expect(page.locator(".sidebar.collapsed")).toBeVisible();

  // Leave it expanded again for any other test that reuses this browser context.
  await page.getByTestId("sidebar-collapse-toggle").click();
  await expect(page.locator(".sidebar.collapsed")).toHaveCount(0);
});

test("the theme toggle switches between dark and light", async ({ page }) => {
  // Every test starts from the same frozen storageState (see auth.setup.ts),
  // captured before anything ever touched the theme - dark is the app's
  // deterministic default (useTheme.ts) whenever localStorage has no
  // preference recorded yet, so this doesn't need to branch on it.
  const html = page.locator("html");
  await expect(html).toHaveClass(/blink-dark/);

  await page.getByTestId("theme-toggle").click();
  await expect(html).not.toHaveClass(/blink-dark/);

  await page.getByTestId("theme-toggle").click();
  await expect(html).toHaveClass(/blink-dark/);
});
