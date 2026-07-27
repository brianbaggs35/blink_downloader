import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.goto("/ai");
  await expect(page.getByRole("heading", { name: "AI", exact: true })).toBeVisible();
});

test("reflects the two seeded analyses instead of the empty state", async ({ page }) => {
  await expect(page.getByTestId("ai-empty")).toBeHidden();
  await expect(page.getByTestId("suspicion-bar")).toBeVisible();
});
