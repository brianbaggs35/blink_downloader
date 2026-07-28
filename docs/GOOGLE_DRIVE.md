# Connecting Google Drive

Archives clip video to your own Google Drive via OAuth. Since this is a
self-hosted app, you're creating and owning a small OAuth client in your own
Google Cloud project — there's no shared "Blink AI Security" app to consent
to, and Google never sees your clips.

## 1. Create a Google Cloud project (if you don't have one)

In the [Google Cloud Console](https://console.cloud.google.com/), create a
new project (or reuse an existing personal one — this doesn't need to be
anything fancy).

## 2. Configure the OAuth consent screen (now called "Google Auth Platform")

Google reorganized this flow into a few tabs under **APIs & Services →
Google Auth Platform** (the console still calls the underlying concept an
"OAuth consent screen," but the page itself is now split up):

1. **Branding** — set an app name and support email. Anything reasonable
   works; only you will ever see this consent screen.
2. **Audience** — choose **External** (this app isn't tied to a Google
   Workspace organization) and, further down, add your own Google account
   under **Test users**. This keeps the app in "Testing" publishing status,
   which is enough to use it yourself — see the callout below about what
   that means long-term.
3. **Data Access** — click **Add or remove scopes** and add
   `https://www.googleapis.com/auth/drive.file`. This is the *only* scope
   the app requests.

### Why `drive.file` specifically

`drive.file` is Google's narrowest Drive scope: it only grants access to
files and folders that this app itself creates (or that you explicitly pick
through Google's own file picker) — not your whole Drive. This app never
asks for the broad `drive` scope, so a compromised or misbehaving OAuth
client here can't read anything else in your Drive. `drive.file` is also
classified as a **non-sensitive** scope, which matters for the next step.

### Testing vs. Production, and why it matters here

Apps left in **Testing** publishing status get refresh tokens that Google
hard-expires after **7 days** — after that, archiving to Drive silently
starts failing until you re-run the OAuth consent flow. For a normal
(sensitive/restricted-scope) app, avoiding this means going through Google's
app verification review, which can take days to weeks — a lot of friction
for something only you will ever use.

Because `drive.file` is non-sensitive, none of that applies here: go to
**Audience** and click **Publish app**. This flips the app to "In
production" — with a non-sensitive-only scope, that's a self-service button
click, not a review process — and refresh tokens stop expiring on the
7-day timer.

## 3. Create an OAuth Client ID

Under **Google Auth Platform → Clients**, create a new OAuth client of type
**Web application**. Add this exact redirect URI (the Integrations page's
help dialog shows this with your actual server's hostname already filled
in):

```
https://<your-server>/api/settings/storage-integrations/google-drive/oauth/callback
```

Copy the generated **Client ID** and **Client Secret** — you'll need both in
the next step. If you lose the secret afterward, you can't retrieve that
same value again, but generating a new one (the client's overflow menu →
**Regenerate secret**) and re-entering it works fine.

## 4. Enter the credentials and connect

On the **Integrations** page, expand the Google Drive card, enable it, and
enter the Client ID and Client Secret, then save. Click **Connect with
Google** and approve access on Google's own sign-in/consent screen — you'll
be redirected back once the connection completes.

## 5. Pick a folder

Credentials only get you connected — they don't decide where clips land.
Once Google Drive shows **Connected**, go to the **Storage** tab and use its
folder browser to create or pick the Drive folder new archives upload into
(defaults to My Drive's root if you never pick one). See
[docs/STORAGE.md](STORAGE.md) for how local vs. archived clip placement
works overall.

## Re-authorizing from scratch

If you ever need to reconnect (a new client, a revoked grant, testing), undo
the existing grant first at <https://myaccount.google.com/permissions> —
Google only issues a new refresh token on a consent screen it considers
"fresh." Then click **Connect with Google** again on the Integrations page.
