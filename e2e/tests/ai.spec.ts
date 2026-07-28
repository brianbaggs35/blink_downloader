import { expect, seededCameras, test } from "../fixtures";

test.beforeEach(async ({ page }) => {
  await page.goto("/ai");
  await expect(page.getByRole("heading", { name: "AI", exact: true })).toBeVisible();
});

test("reflects the two seeded analyses instead of the empty state", async ({ page }) => {
  await expect(page.getByTestId("ai-empty")).toBeHidden();
  await expect(page.getByTestId("suspicion-bar")).toBeVisible();
  await expect(page.getByText("Escalated to Tier 2")).toBeVisible();
  await expect(page.getByText("Vehicle proximity breaches")).toBeVisible();
});

test("links to AI Provider settings for an admin", async ({ page }) => {
  await page.getByTestId("go-ai-settings").click();
  await expect(page.getByTestId("ai-provider-form")).toBeVisible();
});

test("submitting feedback on a clip is reflected in the accuracy stats", async ({ page }) => {
  // No feedback has been recorded on this fresh clip yet - the empty prompt
  // shows instead of an accuracy breakdown.
  await expect(page.getByTestId("no-feedback")).toBeVisible();

  // The front door's routine (non-suspicious, unrecognized) clip is the
  // oldest of its three - clips list newest-first, so it's reliably last
  // once filtered to just that camera.
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Library", exact: true })).toBeVisible();
  await page.getByTestId("camera-filter").click();
  await page.getByRole("option", { name: seededCameras.frontDoor }).click();
  await page.getByTestId("clip-card").last().click();

  await expect(page.getByTestId("clip-modal")).toBeVisible();
  await expect(page.getByTestId("analysis-body")).toBeVisible();
  await page.getByTestId("feedback-correct").click();
  await expect(page.getByTestId("feedback-thanks")).toBeVisible();
  await page.keyboard.press("Escape");

  await page.goto("/ai");
  await expect(page.getByRole("heading", { name: "AI", exact: true })).toBeVisible();
  await expect(page.getByTestId("no-feedback")).toBeHidden();
  await expect(page.getByText(/Accuracy \(\d+ rated\)/)).toBeVisible();
  await expect(page.getByText("Confirmed correct")).toBeVisible();
});
