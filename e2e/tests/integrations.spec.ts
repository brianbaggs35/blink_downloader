import { expect, storageStatePath, test } from "../fixtures";

test.use({ storageState: storageStatePath("admin") });

test.beforeEach(async ({ page }) => {
  await page.goto("/integrations");
  await expect(page.getByRole("heading", { name: "Integrations", exact: true })).toBeVisible();
});

test("searching narrows the integration cards shown", async ({ page }) => {
  // The cards depend on an API call that resolves after the (immediately
  // rendered, static) heading - wait for one before counting, rather than
  // racing whichever finished loading first.
  await expect(page.getByTestId("integration-card-s3")).toBeVisible();
  const cardsBefore = await page.getByTestId(/^integration-card-/).count();
  expect(cardsBefore).toBeGreaterThanOrEqual(3);

  await page.getByTestId("integrations-search").fill("drive");
  await expect(page.getByTestId("integration-card-google_drive")).toBeVisible();
  await expect(page.getByTestId("integration-card-s3")).toBeHidden();

  await page.getByTestId("integrations-search").fill("");
  await expect(page.getByTestId(/^integration-card-/)).toHaveCount(cardsBefore);
});

test("shows how-to-connect help for a provider", async ({ page }) => {
  await page.getByTestId("integration-help-s3").click();
  await expect(page.getByTestId("help-dialog-s3")).toBeVisible();
  await expect(page.getByTestId("help-dialog-s3")).toContainText("IAM");
});

test("filtering by category still shows every seeded integration (all three share one category)", async ({
  page,
}) => {
  // Wait for the async-loaded cards before taking the (non-retrying) count
  // baseline below - without this, a slow response can race ahead of the
  // fetch and land the baseline on 0.
  await expect(page.getByTestId("integration-card-s3")).toBeVisible();
  const cardCount = await page.getByTestId(/^integration-card-/).count();
  // A SelectButton, not a dropdown - every option renders as its own inline
  // button already, nothing to open first. Every seeded integration is
  // catalogued under "Storage", so this doesn't narrow anything visually,
  // but it's a real, distinct code path from the search-text filter (the
  // other half of filteredIntegrations' &&).
  await page
    .getByTestId("integrations-category-filter")
    .getByRole("button", { name: "Storage" })
    .click();
  await expect(page.getByTestId(/^integration-card-/)).toHaveCount(cardCount);
});

test("expanding a provider's form and clicking Configure again collapses it", async ({ page }) => {
  await page.getByTestId("integration-configure-s3").click();
  await expect(page.getByTestId("integration-form-s3")).toBeVisible();
  await page.getByTestId("integration-configure-s3").click();
  await expect(page.getByTestId("integration-form-s3")).toBeHidden();
});

test("running connection tests with nothing connected reports nothing to test", async ({ page }) => {
  await page.getByTestId("test-all-integrations").click();
  // Every provider is disabled by default (see fixtures.storage_integration_settings
  // resetting to nothing connected before every test) - build_*_client()
  // returns null for each, so testResults never gets populated at all.
  await expect(page.getByTestId(/^integration-test-result-/)).toHaveCount(0);
});

test("connecting and disconnecting shows a toast from the OAuth-callback query params", async ({
  page,
}) => {
  // Real Google/Microsoft OAuth can't complete in this environment (see
  // connectOAuthProvider's real window.location.href redirect) - but the
  // *return* leg is just this page reading its own query params on mount,
  // fully testable by landing on it directly the way the real callback
  // redirect would.
  await page.goto("/integrations?connected=google_drive");
  await expect(page.getByText("Google Drive connected")).toBeVisible();

  await page.goto("/integrations?error=onedrive");
  await expect(page.getByText("Could not connect Microsoft OneDrive")).toBeVisible();
  await expect(
    page.getByText("The connection attempt failed or was cancelled. Please try again."),
  ).toBeVisible();
});

test("configures Google Drive and OneDrive up to 'Needs attention', including the clear-secret checkbox", async ({
  page,
}) => {
  for (const [key, clientIdTestid, secretTestid, connectTestid, clearTestid, saveTestid] of [
    [
      "google_drive",
      "drive-client-id",
      "drive-client-secret",
      "drive-connect",
      "drive-clear-secret",
      "integration-save-google_drive",
    ],
    [
      "onedrive",
      "onedrive-client-id",
      "onedrive-client-secret",
      "onedrive-connect",
      "onedrive-clear-secret",
      "integration-save-onedrive",
    ],
  ] as const) {
    await page.getByTestId(`integration-help-${key}`).click();
    await expect(page.getByTestId(`help-dialog-${key}`)).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByTestId(`help-dialog-${key}`)).toBeHidden();

    await page.getByTestId(`integration-configure-${key}`).click();
    await expect(page.getByTestId(`integration-form-${key}`)).toBeVisible();

    const enabledSwitch = page.getByTestId(`${key === "google_drive" ? "drive" : "onedrive"}-enabled`);
    await enabledSwitch.locator("input").check();
    await page.getByTestId(clientIdTestid).fill(`${key}-client-id-e2e`);
    // Not yet saved - Connect needs both a client id *and* a previously
    // saved secret (current?.*_client_secret_set), so it's still disabled.
    await expect(page.getByTestId(connectTestid)).toBeDisabled();

    await page.getByTestId(secretTestid).locator("input").fill(`${key}-client-secret-e2e`);
    await page.getByTestId(saveTestid).click();
    // .last(): this loop saves four times total (two providers x two saves
    // each) - a still-lingering earlier toast with the same text would
    // otherwise make this locator ambiguous (strict-mode violation), so
    // target whichever one just appeared.
    await expect(page.getByText("Integration saved").last()).toBeVisible();
    await expect(page.getByTestId(`integration-status-${key}`)).toHaveText("Needs attention");

    // Now that a secret is saved, Connect is enabled (still never clicked -
    // it's a real, un-mockable OAuth redirect, see the test above).
    await expect(page.getByTestId(connectTestid)).toBeEnabled();

    await expect(page.getByTestId(clearTestid)).toBeVisible();
    await page.getByTestId(clearTestid).locator("input").check();
    await page.getByTestId(saveTestid).click();
    await expect(page.getByText("Integration saved").last()).toBeVisible();
    // Clearing the secret drops *_client_secret_set back to false - Connect
    // (which needs it) goes back to disabled, and the checkbox itself
    // disappears since there's no longer a saved secret to offer clearing.
    await expect(page.getByTestId(connectTestid)).toBeDisabled();
    await expect(page.getByTestId(clearTestid)).toHaveCount(0);
  }
});

test("configures and saves S3, and the connection reflects on the Storage page and Library's bulk bar", async ({
  page,
}) => {
  await page.goto("/storage");
  await expect(page.getByRole("heading", { name: "Storage", exact: true })).toBeVisible();
  await expect(page.getByTestId("backend-card-local")).toBeVisible();
  // Only connected providers show on this page (see StorageView's own
  // isConnected() filtering) - none of the cloud backends are connected yet
  // at this point in the flow, so their cards aren't rendered at all.
  await expect(page.getByTestId("backend-card-s3")).toHaveCount(0);
  await expect(page.getByTestId("backend-card-google_drive")).toHaveCount(0);
  await expect(page.getByTestId("backend-card-onedrive")).toHaveCount(0);

  await page.goto("/integrations");
  await expect(page.getByRole("heading", { name: "Integrations", exact: true })).toBeVisible();
  await page.getByTestId("integration-configure-s3").click();
  await expect(page.getByTestId("integration-form-s3")).toBeVisible();

  await page.getByTestId("s3-enabled").locator("input").check();
  await page.getByTestId("s3-bucket").fill("e2e-clips-bucket");
  await page.getByTestId("s3-region").fill("us-east-1");
  await page.getByTestId("s3-access-key").locator("input").fill("AKIAEXAMPLEKEY");
  await page.getByTestId("s3-secret-key").locator("input").fill("supersecretexamplekey");
  await page.getByTestId("integration-save-s3").click();

  await expect(page.getByTestId("integration-status-s3")).toHaveText("Connected");

  await page.goto("/storage");
  await expect(page.getByRole("heading", { name: "Storage", exact: true })).toBeVisible();
  // The card only rendering at all *is* the "connected" signal now (see the
  // isBackendVisible()/visibleBackends filtering above) - there's no
  // separate status tag to check once every visible card is, by
  // construction, already connected.
  await expect(page.getByTestId("backend-card-s3")).toBeVisible();

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Library", exact: true })).toBeVisible();
  // Archiving needs a clip that's actually downloaded and won't be yanked
  // out from under it mid-test. The newest clips are seed.py's disposable
  // batch, deliberately reserved for library.spec.ts's own delete/bulk-delete
  // tests to consume concurrently - grabbing .first() here would race those
  // tests over the same clip. .last() (the oldest fixture clip) is never
  // touched by any delete test, so it's stable to archive here regardless of
  // what else is running in parallel.
  const downloadedCard = page
    .getByTestId("clip-card")
    .filter({ hasNotText: "Downloading…" })
    .last();
  await downloadedCard.getByTestId("clip-select").click();
  await expect(page.getByTestId("bulk-archive")).toBeVisible();
  await expect(page.getByTestId("bulk-archive-destination")).toBeVisible();

  await page.getByTestId("bulk-archive").click();
  await expect(page.getByText(/Queued 1 clip\(s\) to archive/)).toBeVisible();
});

test("the Storage page's auto-archive picker only offers connected destinations, and hints to connect one when there are none", async ({
  page,
}) => {
  // storage_integration_settings resets to "nothing connected" before every
  // test (see ../fixtures' auto-reset fixture), so no setup is needed here.
  await page.goto("/storage");
  await expect(page.getByRole("heading", { name: "Storage", exact: true })).toBeVisible();
  await page.getByTestId("edit-auto-archive").click();
  await expect(page.getByTestId("auto-archive-backend")).toBeVisible();

  // The destination picker must not offer an unconnected cloud provider at
  // all (rather than offering it and then warning), so the only option is
  // Local disk.
  await page.getByTestId("auto-archive-backend").click();
  await expect(page.getByRole("option", { name: "Google Drive" })).toHaveCount(0);
  await expect(page.getByRole("option", { name: "Amazon S3" })).toHaveCount(0);
  await expect(page.getByRole("option", { name: "Local disk" })).toBeVisible();
  await page.keyboard.press("Escape");

  await expect(page.getByTestId("storage-no-providers-connected")).toBeVisible();
  await page.getByTestId("storage-go-to-integrations").click();
  await expect(page.getByRole("heading", { name: "Integrations", exact: true })).toBeVisible();
});

test("Storage page: browse a connected cloud backend (list/create/rename/delete/select), mocked", async ({
  page,
}) => {
  // Connect S3 with fake credentials first, same as the other tests here -
  // real listing/creating/renaming/deleting against S3 needs a real bucket
  // and real credentials neither of which exist in this stack, so every
  // one of those calls is mocked below. What's under test is
  // CloudFolderBrowserDialog's own real frontend code (breadcrumbs, the
  // create/rename/delete forms, the loading/error states) reacting to
  // realistic responses - not a real AWS round trip, which the
  // "nothing connected" and "test-all-integrations" tests already cover
  // for the parts of this page that stay real.
  await page.getByTestId("integration-configure-s3").click();
  await page.getByTestId("s3-enabled").locator("input").check();
  await page.getByTestId("s3-bucket").fill("e2e-clips-bucket");
  await page.getByTestId("s3-region").fill("us-east-1");
  await page.getByTestId("s3-access-key").locator("input").fill("AKIAEXAMPLEKEY");
  await page.getByTestId("s3-secret-key").locator("input").fill("supersecretexamplekey");
  await page.getByTestId("integration-save-s3").click();
  await expect(page.getByTestId("integration-status-s3")).toHaveText("Connected");

  let folders = [{ id: "folder-a", name: "Existing Folder" }];
  await page.route("**/api/settings/storage-integrations/s3/browse**", async (route) => {
    const method = route.request().method();
    if (method === "GET") {
      await route.fulfill({ json: { folders } });
    } else if (method === "POST") {
      const body = route.request().postDataJSON() as { name: string };
      folders = [...folders, { id: "folder-new", name: body.name }];
      await route.fulfill({ json: { folders } });
    } else {
      // PATCH (rename) / DELETE both return void on success, then the
      // component re-fetches via the same GET handler above.
      await route.fulfill({ status: 204 });
    }
  });

  await page.goto("/storage");
  await expect(page.getByRole("heading", { name: "Storage", exact: true })).toBeVisible();
  await page.getByTestId("backend-browse-s3").click();
  const dialog = page.getByTestId("cloud-browse-modal");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByTestId("cloud-browse-entries")).toBeVisible();
  await expect(dialog.getByTestId("cloud-browse-entry-Existing Folder")).toBeVisible();

  await dialog.getByTestId("cloud-browse-new-folder-name").fill("New Folder");
  await dialog.getByTestId("cloud-browse-create-folder").click();
  await expect(dialog.getByTestId("cloud-browse-entry-New Folder")).toBeVisible();

  await dialog.getByTestId("cloud-browse-rename-Existing Folder").click();
  await dialog.getByTestId("cloud-browse-rename-input-Existing Folder").fill("Renamed Folder");
  await dialog.getByTestId("cloud-browse-rename-confirm-Existing Folder").click();
  // The mocked GET always returns the same fixed list, so this just proves
  // the rename round trip completed and the dialog left rename mode
  // cleanly - not that the name visibly changed.
  await expect(dialog.getByTestId("cloud-browse-rename-input-Existing Folder")).toHaveCount(0);
  await expect(dialog.getByTestId("cloud-browse-action-error")).toHaveCount(0);

  await dialog.getByTestId("cloud-browse-delete-New Folder").click();
  await page
    .getByRole("alertdialog", { name: "Delete folder", exact: true })
    .getByRole("button", { name: "Delete" })
    .click();
  await expect(dialog.getByTestId("cloud-browse-action-error")).toHaveCount(0);

  // Navigate into a folder and back out via the breadcrumb, then select the
  // root itself - the same round trip StorageView.onCloudFolderSelected's
  // s3 branch (setting s3_prefix) depends on.
  await dialog.getByTestId("cloud-browse-entry-Existing Folder").click();
  await expect(dialog.getByTestId("cloud-browse-crumb-1")).toContainText("Existing Folder");
  await dialog.getByTestId("cloud-browse-crumb-0").click();
  await expect(dialog.getByTestId("cloud-browse-entry-Existing Folder")).toBeVisible();

  await dialog.getByTestId("cloud-browse-select").click();
  await expect(dialog).toBeHidden();
});

test("CloudFolderBrowserDialog shows a real error when S3 listing genuinely fails, and Cancel closes it", async ({
  page,
}) => {
  // No mocking here - real fake credentials against a real (nonexistent)
  // bucket, so the list call genuinely fails the same way it would for a
  // real misconfigured account.
  await page.getByTestId("integration-configure-s3").click();
  await page.getByTestId("s3-enabled").locator("input").check();
  await page.getByTestId("s3-bucket").fill("e2e-clips-bucket");
  await page.getByTestId("s3-region").fill("us-east-1");
  await page.getByTestId("s3-access-key").locator("input").fill("AKIAEXAMPLEKEY");
  await page.getByTestId("s3-secret-key").locator("input").fill("supersecretexamplekey");
  await page.getByTestId("integration-save-s3").click();
  await expect(page.getByTestId("integration-status-s3")).toHaveText("Connected");

  await page.goto("/storage");
  await page.getByTestId("backend-browse-s3").click();
  const dialog = page.getByTestId("cloud-browse-modal");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByTestId("cloud-browse-error")).toBeVisible();
  await expect(dialog.getByTestId("cloud-browse-entries")).toHaveCount(0);

  await dialog.getByTestId("cloud-browse-cancel").click();
  await expect(dialog).toBeHidden();
});

test("Storage page: auto-archive policy save/cancel, and the quota gauge appearing after a limit is set", async ({
  page,
}) => {
  // Connect S3 first so the auto-archive backend picker has a real
  // non-Local option to choose from and save.
  await page.getByTestId("integration-configure-s3").click();
  await page.getByTestId("s3-enabled").locator("input").check();
  await page.getByTestId("s3-bucket").fill("e2e-clips-bucket");
  await page.getByTestId("s3-region").fill("us-east-1");
  await page.getByTestId("s3-access-key").locator("input").fill("AKIAEXAMPLEKEY");
  await page.getByTestId("s3-secret-key").locator("input").fill("supersecretexamplekey");
  await page.getByTestId("integration-save-s3").click();
  await expect(page.getByTestId("integration-status-s3")).toHaveText("Connected");

  await page.goto("/storage");
  await expect(page.getByRole("heading", { name: "Storage", exact: true })).toBeVisible();

  // Auto-archive: open, cancel without saving - proves cancelEditAutoArchive()
  // closes the form without a network call.
  await page.getByTestId("edit-auto-archive").click();
  await expect(page.getByTestId("auto-archive-form")).toBeVisible();
  await page.getByTestId("cancel-auto-archive").click();
  await expect(page.getByTestId("auto-archive-form")).toBeHidden();

  // Reopen and actually save this time.
  await page.getByTestId("edit-auto-archive").click();
  await page.getByTestId("auto-archive-backend").click();
  await page.getByRole("option", { name: "Amazon S3" }).click();
  await page.getByTestId("auto-archive-after-days").locator("input").fill("14");
  await page.getByTestId("save-auto-archive").click();
  await expect(page.getByTestId("auto-archive-form")).toBeHidden();

  await page.reload();
  await page.getByTestId("edit-auto-archive").click();
  await expect(page.getByTestId("auto-archive-backend")).toContainText("Amazon S3");
  await expect(page.getByTestId("auto-archive-after-days").locator("input")).toHaveValue("14");
  await page.getByTestId("cancel-auto-archive").click();

  // Quota: unset by default (seed never sets one) - set a limit, which
  // flips storage-quota-unset over to a real gauge.
  await expect(page.getByTestId("storage-quota-unset")).toBeVisible();
  await expect(page.getByTestId("storage-quota-gauge")).toHaveCount(0);

  await page.getByTestId("edit-storage-quota").click();
  await expect(page.getByTestId("storage-quota-form")).toBeVisible();
  await page.getByTestId("storage-quota-gb").locator("input").fill("50");
  await page.getByTestId("save-storage-quota").click();
  await expect(page.getByTestId("storage-quota-form")).toBeHidden();

  await expect(page.getByTestId("storage-quota-gauge")).toBeVisible();
  await expect(page.getByTestId("storage-quota-percent")).toBeVisible();
  await expect(page.getByTestId("storage-quota-unset")).toHaveCount(0);

  // Edit again and cancel - proves cancelEditQuota() too, and that the
  // gauge (not the unset message) is what "Edit limit" now reopens from.
  await page.getByTestId("edit-storage-quota").click();
  await page.getByTestId("cancel-storage-quota").click();
  await expect(page.getByTestId("storage-quota-gauge")).toBeVisible();
});

test("Storage page: browse the local backend, create a folder, navigate into and back out of it", async ({
  page,
}) => {
  await page.goto("/storage");
  await expect(page.getByRole("heading", { name: "Storage", exact: true })).toBeVisible();

  await page.getByTestId("backend-browse-local").click();
  await expect(page.getByTestId("storage-browse-modal")).toBeVisible();
  await expect(page.getByTestId("storage-browse-entries")).toBeVisible();

  const folderName = `e2e-folder-${Date.now()}`;
  await page.getByTestId("storage-browse-new-folder-name").fill(folderName);
  await page.getByTestId("storage-browse-create-folder").click();
  // Creating a folder navigates straight into it (empty, nothing to list
  // yet) rather than just adding an entry to the current listing.
  await expect(page.getByTestId("storage-browse-current-path")).toContainText(folderName);

  await page.getByTestId("storage-browse-up").click();
  const entry = page.getByTestId(`storage-browse-entry-${folderName}`);
  await expect(entry).toBeVisible();

  // Now exercise the other direction: navigating in via the entry button.
  await entry.click();
  await expect(page.getByTestId("storage-browse-current-path")).toContainText(folderName);
  await page.getByTestId("storage-browse-up").click();
  await expect(entry).toBeVisible();

  await page.getByTestId(`storage-browse-delete-${folderName}`).click();
  const confirmDialog = page.getByRole("alertdialog", { name: "Delete folder", exact: true });
  await confirmDialog.getByRole("button", { name: "Delete" }).click();
  await expect(entry).toHaveCount(0);

  await page.getByTestId("storage-browse-cancel").click();
  await expect(page.getByTestId("storage-browse-modal")).toBeHidden();
});

test("Storage page: rename a folder, cancelling once before confirming", async ({ page }) => {
  await page.goto("/storage");
  await expect(page.getByRole("heading", { name: "Storage", exact: true })).toBeVisible();

  await page.getByTestId("backend-browse-local").click();
  await expect(page.getByTestId("storage-browse-modal")).toBeVisible();

  const originalName = `e2e-rename-src-${Date.now()}`;
  await page.getByTestId("storage-browse-new-folder-name").fill(originalName);
  await page.getByTestId("storage-browse-create-folder").click();
  await expect(page.getByTestId("storage-browse-current-path")).toContainText(originalName);
  await page.getByTestId("storage-browse-up").click();

  const originalEntry = page.getByTestId(`storage-browse-entry-${originalName}`);
  await expect(originalEntry).toBeVisible();

  // Start a rename, then back out of it - the entry should be untouched.
  await page.getByTestId(`storage-browse-rename-${originalName}`).click();
  const renameInput = page.getByTestId(`storage-browse-rename-input-${originalName}`);
  await expect(renameInput).toBeVisible();
  const renamedName = `e2e-rename-dst-${Date.now()}`;
  await renameInput.fill(renamedName);
  await page.getByTestId(`storage-browse-rename-cancel-${originalName}`).click();
  await expect(renameInput).toHaveCount(0);
  await expect(originalEntry).toBeVisible();

  // Now actually go through with it.
  await page.getByTestId(`storage-browse-rename-${originalName}`).click();
  await page.getByTestId(`storage-browse-rename-input-${originalName}`).fill(renamedName);
  await page.getByTestId(`storage-browse-rename-confirm-${originalName}`).click();
  await expect(originalEntry).toHaveCount(0);
  const renamedEntry = page.getByTestId(`storage-browse-entry-${renamedName}`);
  await expect(renamedEntry).toBeVisible();

  // Clean up - disk state isn't reset between tests the way the database is.
  await page.getByTestId(`storage-browse-delete-${renamedName}`).click();
  const confirmDialog = page.getByRole("alertdialog", { name: "Delete folder", exact: true });
  await confirmDialog.getByRole("button", { name: "Delete" }).click();
  await expect(renamedEntry).toHaveCount(0);

  await page.getByTestId("storage-browse-cancel").click();
  await expect(page.getByTestId("storage-browse-modal")).toBeHidden();
});
