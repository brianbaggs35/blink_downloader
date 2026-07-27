# Storage: local disk, cloud archiving, and integrations

Clips always download to local disk first (`Settings > General > Storage`,
`/api/settings/storage`) — that part is unconditional and always was. This
document covers what's optional on top of it: archiving a clip's video to a
cloud provider, and the Integrations page that connects one.

## Scope: clip video only

Archiving moves **clip video bytes** (`Clip.storage_path` /
`Clip.storage_backend`) between local disk and a cloud provider. Thumbnails,
vehicle reference photos, and biometrics face crops/samples are never
touched — they stay local always, regardless of where a clip's video lives.
Thumbnails are cheap to regenerate from the clip via ffmpeg; the others are
small reference images nobody asked to archive. This is a deliberate scope
boundary, not an oversight.

## Archive / restore: one canonical location, not a cached copy

A clip's video lives in exactly one place at a time — local disk, or one
cloud provider. "Archive" reads the local file, uploads it, deletes the
local copy, and flips `storage_backend`/`storage_path` to point at the
remote key/file ID. "Restore" is the mirror image. There is no "keep both"
mode; this keeps the mental model simple; a clip's `storage_path` is always
"the one place this clip's bytes canonically live," matching how the
downloader itself already treats local storage.

If archiving's local cleanup fails after the upload already succeeded (or
restoring's remote cleanup fails after the local write already succeeded),
that failure is logged and swallowed rather than raised — the primary copy
is already safely in place by that point, and a leftover secondary copy is
wasted space, not a correctness problem.

### Auto-archiving new downloads

`Settings > Archived` has a single setting: where a newly-downloaded clip
should end up. Left at "local disk" (the default), nothing changes. Pointed
at a cloud provider, every clip is archived automatically right after it
finishes AI analysis — the video stays on local disk for exactly as long as
analysis needs to read it (keyframe extraction happens against the local
file), then gets archived the same way a manual archive action would. If
automatic analysis is turned off entirely, archiving happens immediately
after download instead, since no analysis step exists to trigger it
afterward.

## Download links: the same trust model, two different mechanisms

Downloading an archived clip (from the Storage tab, or the Library's bulk
download) needs a link that works without asking the browser to carry an
admin session's cookies. Both providers get a link that is, conceptually,
the same thing — a time-limited bearer token embedded in a URL — but built
two different ways:

- **S3**: a real, cloud-native presigned URL (`boto3`'s
  `generate_presigned_url`, SigV4-signed). The browser talks to AWS
  directly; our backend is not in the download path at all.
- **Google Drive / OneDrive**: neither provider has an equivalent
  "presigned URL" primitive without making the file world-readable first,
  which was deliberately avoided. Instead we issue our own encrypted,
  self-contained token (`{clip_id, backend, expires_at}`, Fernet-encrypted)
  embedded in a URL pointing back at our own backend
  (`GET /api/storage/download/{token}`), which decrypts and validates the
  token, then proxies the file down from the provider using our own stored
  OAuth credentials.

Both links expire after one hour and are single-purpose (only usable for
the one clip they were minted for).

## Connecting a provider

All three providers are configured from the **Integrations** page (left
nav, under "Archive"). Search and category-filter across integrations
there; click a card's "Configure" to expand its settings form inline.

### Amazon S3

1. In the AWS Console, create an S3 bucket (any region) to hold archived
   clips.
2. Create an IAM user (or role) with a policy granting `s3:PutObject`,
   `s3:GetObject`, and `s3:DeleteObject` on that bucket. Nothing broader is
   needed.
3. Generate an access key for that user.
4. On the Integrations page, enable S3 and enter the bucket name, region,
   access key ID, and secret access key, then save. An optional key prefix
   keeps a shared bucket's clips under e.g. `blink-clips/` instead of the
   bucket root.

S3 credentials are static (no OAuth dance) — "Save" is the whole connect
flow. Use "Test all connections" on the Integrations page to confirm the
bucket is reachable before relying on it.

### Google Drive

1. In the [Google Cloud Console](https://console.cloud.google.com/apis/credentials),
   create an OAuth 2.0 Client ID of type "Web application".
2. Add this exact redirect URI to the client (the Integrations page's help
   dialog shows this with your actual server's hostname filled in):
   `https://<your-server>/api/settings/storage-integrations/google-drive/oauth/callback`
3. Enter the Client ID and Client Secret on the Integrations page and save.
4. Click "Connect with Google" and approve access on Google's own
   sign-in/consent screen. You'll be redirected back once the connection
   completes.
5. An optional Drive folder ID scopes uploads to a specific folder instead
   of Drive's root.

If you ever need to re-authorize from scratch, revoke the app's access at
<https://myaccount.google.com/permissions> first — Google only returns a
refresh token on a consent screen it considers "fresh."

### Microsoft OneDrive

1. In the [Microsoft Entra admin center](https://entra.microsoft.com),
   register a new application.
2. Add this exact redirect URI (platform: Web):
   `https://<your-server>/api/settings/storage-integrations/onedrive/oauth/callback`
3. Under API permissions, add the delegated `Files.ReadWrite` Microsoft
   Graph permission.
4. Create a client secret. Enter the Application (client) ID and the
   secret's value (not its ID) on the Integrations page and save.
5. Click "Connect with Microsoft" and approve access on Microsoft's own
   sign-in screen.
6. An optional folder path (default `BlinkClips`) scopes uploads to a
   specific OneDrive folder.

## Implementation notes

- `app/integrations/cloud.py` — S3 via `boto3` (explicit SigV4, HTTPS-only).
  Google Drive via `google-auth-oauthlib` + `google-api-python-client`
  (automatic token refresh, resumable upload/download). OneDrive's OAuth
  token lifecycle via `msal`; actual file operations go straight to
  Microsoft Graph over `httpx`, since Microsoft has no separate "OneDrive
  files" SDK — this split is their own documented pattern, not a shortcut.
- `app/integrations/service.py` — settings CRUD (tri-state secrets: a
  `null` update payload field leaves the stored secret untouched, an empty
  string clears it, anything else replaces it) and OAuth CSRF state
  handling.
- `app/integrations/archive.py` — the archive/restore orchestration and
  temporary-link issuance described above.
- All credentials (S3 keys, OAuth client secrets, OAuth refresh tokens) are
  encrypted at rest with the same Fernet `SecretBox` used for Blink
  credentials and alert webhook URLs — never stored or logged in plaintext.
