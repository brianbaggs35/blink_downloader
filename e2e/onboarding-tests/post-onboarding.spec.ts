import { expect, test } from "@playwright/test";

import { storageStatePath } from "../fixtures";

// Cheap assertions about what a freshly-onboarded account looks like -
// reuses onboarding.setup.ts's saved session instead of re-running the
// wizard (which can only ever happen once per database - see that file's
// own comment). Deliberately not using ../fixtures' auto-resetting `test`:
// see onboarding.setup.ts for why domain-data resets don't belong in this
// stack at all.
test.use({ storageState: storageStatePath("onboarding") });

test("Library shows the no-Blink-linked empty state, not any seeded demo data", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Library", exact: true })).toBeVisible();
  await expect(page.getByText("Link your Blink account")).toBeVisible();
  await expect(page.getByTestId("go-settings")).toBeVisible();
  await expect(page.getByTestId("clip-card")).toHaveCount(0);
});

test("the onboarded account is a superuser, with the submitted display name", async ({
  page,
}) => {
  await page.goto("/");
  // Admin-only nav items: only reachable at all if POST /api/setup really
  // did create this account with is_superuser=true (see api/setup.py).
  await expect(page.getByRole("link", { name: "Connect", exact: true })).toBeVisible();

  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "Settings", exact: true })).toBeVisible();
  await expect(page.getByTestId("display-name")).toHaveValue("Onboarding E2E Admin");
});
