# Connecting Microsoft OneDrive

Archives clip video to your own OneDrive via OAuth, through Microsoft Graph.
Like Google Drive, this is your own app registration in your own Microsoft
Entra tenant (or personal Microsoft account) — there's no shared app to
consent to.

## 1. Register an application

In the [Microsoft Entra admin center](https://entra.microsoft.com), go to
**Identity → Applications → App registrations → New registration**. Give it
any name; leave the redirect URI blank for now (configured next). Note the
**Application (client) ID** on the overview page once it's created.

## 2. Add the redirect URI

Under **Manage → Authentication**, add a redirect URI. Choose **Web** as the
platform, and enter this exact URI (the Integrations page's help dialog
shows this with your actual server's hostname already filled in):

```
https://<your-server>/api/settings/storage-integrations/onedrive/oauth/callback
```

## 3. Add the API permission

Under **Manage → API permissions → Add a permission → Microsoft Graph →
Delegated permissions**, add `Files.ReadWrite`.

### Why `Files.ReadWrite` and not something narrower

Microsoft Graph does offer a narrower delegated permission,
`Files.ReadWrite.AppFolder`, which automatically confines an app to a single
dedicated `Apps/<AppName>` folder — no broader Drive access at all. It isn't
used here for two reasons: it's only valid for **personal** Microsoft
accounts (Microsoft hasn't extended it to work/school OneDrive for
Business), and — more fundamentally — it can only ever see that one
dedicated folder, which conflicts with the Storage tab's folder browser
letting you pick any existing OneDrive folder you already use. `Files.ReadWrite`
is the least-privilege choice *given that feature*; if you'd rather trade
the folder picker for a strictly app-confined folder, that's a
`Files.ReadWrite.AppFolder`-based setup this app doesn't currently offer.

`Files.ReadWrite` still only grants access to *your own* OneDrive as the
signed-in user (via the delegated/user-context OAuth flow) — never
application-wide access to other users' files, which would be the
separate, far broader `Files.ReadWrite.All` **application** permission this
app never requests.

## 4. Create a client secret

Under **Manage → Certificates & secrets → Client secrets → New client
secret**, add a description and pick an expiration (Microsoft caps this at
24 months, and no longer offers a "never expires" option). Copy the
**Value** field immediately — unlike the secret's ID, the value is shown
only once and can't be retrieved again later.

Put a reminder somewhere for whatever expiration you pick — when this
secret expires, OneDrive archiving stops working until you generate a new
one and re-enter it.

## 5. Enter the credentials and connect

On the **Integrations** page, expand the Microsoft OneDrive card, enable
it, and enter the Application (client) ID and the secret's **value** (not
its ID), then save. Click **Connect with Microsoft** and approve access on
Microsoft's own sign-in screen.

## 6. Pick a folder

Credentials only get you connected — they don't decide where clips land.
Once OneDrive shows **Connected**, go to the **Storage** tab and use its
folder browser to create or pick the OneDrive folder new archives upload
into (defaults to a `BlinkClips` folder at the root if you never pick one).
See [docs/STORAGE.md](STORAGE.md) for how local vs. archived clip placement
works overall.
