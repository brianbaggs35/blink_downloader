import { expect, storageStatePath, test } from "../fixtures";

test.use({ storageState: storageStatePath("admin") });

test.beforeEach(async ({ page }) => {
  await page.goto("/ai-usage");
  await expect(page.getByRole("heading", { name: "AI Usage", exact: true })).toBeVisible();
});

test("shows the seeded usage totals instead of the empty state", async ({ page }) => {
  await expect(page.getByTestId("usage-empty")).toBeHidden();
  // 6 seeded rows, one of which failed - both real, non-zero KPIs.
  await expect(page.getByText("Total calls")).toBeVisible();
  await expect(page.getByText("Failed calls")).toBeVisible();
  await expect(page.getByText("Frames analyzed today")).toBeVisible();
  await expect(page.getByText("Frames analyzed (all time)")).toBeVisible();
});

test("toggles the daily section between chart and table", async ({ page }) => {
  await expect(page.getByTestId("daily-charts")).toBeVisible();
  await expect(page.getByTestId("daily-table")).toBeHidden();

  await page.getByTestId("daily-view-toggle").getByText("Table").click();
  await expect(page.getByTestId("daily-table")).toBeVisible();
  await expect(page.getByTestId("daily-charts")).toBeHidden();
  // At least one day of seeded usage should show a row with real numbers.
  await expect(page.locator('[data-testid="daily-table"] tbody tr').first()).toBeVisible();

  await page.getByTestId("daily-view-toggle").getByText("Chart").click();
  await expect(page.getByTestId("daily-charts")).toBeVisible();
});

test("toggles the by-provider section between chart and table, with a hover tooltip", async ({
  page,
}) => {
  await expect(page.getByTestId("provider-bars")).toBeVisible();
  // Two providers were seeded (Anthropic and OpenAI).
  const firstBar = page.getByTestId("bar-row-0");
  await expect(firstBar).toBeVisible();
  await expect(page.getByTestId("bar-row-1")).toBeVisible();

  await firstBar.hover();
  await expect(page.getByTestId("bar-tooltip")).toBeVisible();

  await page.getByTestId("provider-view-toggle").getByText("Table").click();
  await expect(page.getByTestId("provider-table")).toBeVisible();
  await expect(page.getByTestId("provider-bars")).toBeHidden();
  await expect(page.locator('[data-testid="provider-table"] tbody tr')).toHaveCount(2);
});

test("links to AI Provider settings for an admin", async ({ page }) => {
  await page.getByTestId("go-ai-settings").click();
  await expect(page.getByTestId("ai-provider-form")).toBeVisible();
});
