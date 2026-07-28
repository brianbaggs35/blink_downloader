import { expect, seededCameras, seededPerson, test } from "../fixtures";

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
  // The checked state above is v-model's own optimistic UI update, not
  // proof the PATCH actually landed - the toggle also disables itself for
  // the duration of that request (PersonDetailPanel.vue's
  // savingNeverMarkSuspicious), so waiting for it to re-enable is what
  // actually guarantees the list view (fetched fresh after navigating back)
  // reflects the change, rather than racing it.
  await expect(toggle).toBeEnabled();

  await page.getByTestId("back-to-people").click();
  await expect(page.getByTestId("trusted-icon")).toBeVisible();

  // Leave it as found for any other test that reuses this seeded person.
  await page.getByText(seededPerson.name).click();
  const cleanupToggle = page.getByTestId("never-mark-suspicious-toggle").locator("input");
  await cleanupToggle.uncheck();
  await expect(cleanupToggle).toBeEnabled();
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

test("creates a new person and deletes it again", async ({ page }) => {
  const name = `E2E Disposable Person ${Date.now()}`;
  await page.getByTestId("open-add-person").click();
  await page.getByTestId("new-person-name").fill(name);
  await page.getByTestId("submit-new-person").click();

  // Lands straight in the new person's (still faceless) detail view. The
  // name also appears in a "Clips where X is recognized..." paragraph
  // further down, so a plain getByText(name) is ambiguous - the heading is
  // the one, unique place it's the actual page title.
  await expect(page.getByTestId("person-detail-panel")).toBeVisible();
  await expect(page.getByRole("heading", { name, exact: true })).toBeVisible();

  await page.getByTestId("delete-person").click();
  const dialog = page.getByRole("alertdialog", { name: "Delete person", exact: true });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText(name);
  await dialog.getByRole("button", { name: "Delete" }).click();

  await expect(page.getByText("Person deleted")).toBeVisible();
  await expect(page.getByTestId("people-grid")).toBeVisible();
  await expect(page.getByText(name)).toBeHidden();
});

test("renames the seeded person, then restores the original name", async ({ page }) => {
  await page.getByText(seededPerson.name).click();
  await expect(page.getByTestId("person-detail-panel")).toBeVisible();

  await page.getByTestId("person-rename-start").click();
  await page.getByTestId("person-name-input").fill(`${seededPerson.name} (renamed)`);
  await page.getByTestId("person-name-save").click();
  // The heading, not getByText - the name also appears in a "Clips where
  // X is recognized..." paragraph on this same view, so a plain text match
  // is ambiguous.
  await expect(
    page.getByRole("heading", { name: `${seededPerson.name} (renamed)`, exact: true }),
  ).toBeVisible();

  // Leave it as found for any other test that looks this person up by name.
  await page.getByTestId("person-rename-start").click();
  await page.getByTestId("person-name-input").fill(seededPerson.name);
  await page.getByTestId("person-name-save").click();
  await expect(page.getByRole("heading", { name: seededPerson.name, exact: true })).toBeVisible();
});

test("cancels an in-progress rename without saving", async ({ page }) => {
  await page.getByText(seededPerson.name).click();
  await page.getByTestId("person-rename-start").click();
  await page.getByTestId("person-name-input").fill("Should not be saved");
  await page.getByTestId("person-name-cancel").click();
  await expect(page.getByRole("heading", { name: seededPerson.name, exact: true })).toBeVisible();
});

test("the enrollment panel walks camera and time-range selection down to a clip picker", async ({
  page,
}) => {
  await page.getByText(seededPerson.name).click();
  await expect(page.getByTestId("person-detail-panel")).toBeVisible();

  await page.getByTestId("enroll-camera-select").click();
  await page.getByRole("option", { name: seededCameras.frontDoor }).click();
  await expect(page.getByTestId("enroll-clip-list")).toBeVisible();

  await page.getByTestId("enroll-clip-list").locator(".clip-item").first().click();
  // Synthetic seed clips are a color-bar test pattern, not a real face, so
  // detection always (correctly) comes back empty here - this is an
  // environmental limit of the fixture data, not a gap in the app. A
  // generous timeout: the very first detection call in a fresh backend
  // process lazily loads the real insightface ONNX model, which can take
  // well over the default 5s under parallel test load.
  await expect(page.getByTestId("picker-scrubber")).toBeVisible();
  await expect(page.getByTestId("picker-no-faces")).toBeVisible({ timeout: 20000 });
});

test("opens Report a missed face from a clip, with the confirm action disabled until a face is picked", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Library", exact: true })).toBeVisible();
  await page.getByTestId("clip-card").first().click();
  await expect(page.getByTestId("clip-modal")).toBeVisible();

  await page.getByTestId("report-missed-face").click();
  await page.getByTestId("report-missed-face-confirm").click();
  await expect(page.getByTestId("report-missed-face-dialog")).toBeVisible();
  await expect(page.getByTestId("picker-scrubber")).toBeVisible();

  const enroll = page.getByRole("button", { name: "Enroll this face" });
  await expect(enroll).toBeDisabled();

  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByTestId("report-missed-face-dialog")).toBeHidden();
});
