import { expect, seededPerson, test } from "../fixtures";

test.beforeEach(async ({ page }) => {
  await page.goto("/biometrics");
  await expect(page.getByRole("heading", { name: "Biometrics", exact: true })).toBeVisible();
});

test("shows the seeded person in the roster", async ({ page }) => {
  await expect(page.getByTestId("people-grid")).toBeVisible();
  await expect(page.getByText(seededPerson.name)).toBeVisible();
});

test("drilling into a person shows their enrolled face sample", async ({ page }) => {
  await page.getByText(seededPerson.name).click();
  await expect(page.getByTestId("person-detail-panel")).toBeVisible();
  await expect(page.getByTestId("face-grid")).toBeVisible();
  await expect(page.locator('[data-testid^="face-item-"]')).toHaveCount(1);

  await page.getByTestId("back-to-people").click();
  await expect(page.getByTestId("people-grid")).toBeVisible();
});

test("opens the add-person dialog", async ({ page }) => {
  await page.getByTestId("open-add-person").click();
  await expect(page.getByTestId("add-person-dialog")).toBeVisible();
  await expect(page.getByTestId("submit-new-person")).toBeDisabled();
  await page.getByTestId("new-person-name").fill("Temporary Test Person");
  await expect(page.getByTestId("submit-new-person")).toBeEnabled();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("add-person-dialog")).toBeHidden();
});
