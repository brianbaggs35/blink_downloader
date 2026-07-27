import { expect, test } from "@playwright/test";

test("shows the empty state when no AI usage has been recorded yet", async ({ page }) => {
  await page.goto("/ai-usage");
  await expect(page.getByRole("heading", { name: "AI Usage", exact: true })).toBeVisible();
  await expect(page.getByTestId("usage-empty")).toBeVisible();
});
