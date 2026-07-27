import { expect, test } from "@playwright/test";

test("shows the empty state when no vehicles are configured yet", async ({ page }) => {
  await page.goto("/vehicles");
  await expect(page.getByRole("heading", { name: "Vehicles", exact: true })).toBeVisible();
  await expect(page.getByTestId("vehicles-empty")).toBeVisible();
  await expect(page.getByTestId("go-vehicle-settings-empty")).toBeVisible();
});
