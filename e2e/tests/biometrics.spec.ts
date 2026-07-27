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

test("toggles never-mark-suspicious for the seeded person", async ({ page }) => {
  await page.getByText(seededPerson.name).click();
  await expect(page.getByTestId("person-detail-panel")).toBeVisible();

  // .check()/.uncheck() are idempotent (a no-op if already in that state),
  // unlike .click() - this suite runs against a persistent, not-reseeded-
  // between-runs database, so a prior run may have left this checked.
  const toggle = page.getByTestId("never-mark-suspicious-toggle").locator("input");
  await toggle.check();
  await expect(toggle).toBeChecked();

  await page.getByTestId("back-to-people").click();
  await expect(page.getByTestId("trusted-icon")).toBeVisible();

  // Leave it as found for any other test that reuses this seeded person.
  await page.getByText(seededPerson.name).click();
  await page.getByTestId("never-mark-suspicious-toggle").locator("input").uncheck();
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
