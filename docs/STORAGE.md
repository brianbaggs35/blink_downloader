# Storage: local disk, cloud archiving, and integrations

Clips always download to local disk first — that part is unconditional and
always was. This document covers what's optional on top of it: archiving a
clip's video to a cloud provider, and the pages involved in setting that up.

## Where things live

Two different places in the UI cooperate here, each with one job:

- **Integrations → Connect** (left nav) — connect a cloud provider: enable
  it, enter credentials, test the connection. Nothing about *where* clips
  go, or the auto-archive policy, lives here.
- **Storage** tab (left nav) — everything about where clips actually live.
  Usage per backend (with an editable quota gauge for local disk), a live
  folder browser for local disk and each *connected* cloud provider — create,
  rename, and delete folders, and pick which one new archives upload into —
  and the auto-archive policy itself: which backend new downloads move to,
  and how long to keep them on local disk first. A cloud provider only
  appears as a folder-pickable/archive-destination option here once it's
  actually connected on the Integrations page.

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

The Storage tab's auto-archive policy card has two settings that together
decide what happens to a newly-downloaded clip: which backend it should end
up on, and how long to leave it on local disk first.

Left at "local disk" (the default), nothing changes — clips just stay put.
Pointed at a cloud provider (only offered once that provider is actually
connected), a clip becomes eligible for archiving right after it finishes AI
analysis — the video stays on local disk for exactly as long as analysis
needs to read it (keyframe extraction happens against the local file). If
automatic analysis is turned off entirely, a clip becomes eligible
immediately after download instead, since no analysis step exists to
trigger it afterward.

"Days to keep clips locally first" then decides *when* that eligible clip
actually moves: `0` (the default) archives it right away, the same way a
manual archive action would; a positive number instead defers the move by
that many days (enqueued as a delayed background job), so a clip stays
readily available on local disk for a while before it's pushed off to
cloud storage.

### Local disk quota

An optional soft budget (GB), set directly from the Storage tab's local disk
card and shown there as a usage gauge — purely informational. Nothing is
deleted, blocked, or auto-archived because you're over it; it's there so you
can see at a glance how close you are, not to enforce a limit.

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
nav): search and category-filter across integrations there, then click a
card's "Configure" to expand its settings form inline — credentials only,
plus a per-provider **Test connection** button and a link to the Storage tab
for picking a folder once you're connected. Each provider also has a
dedicated setup guide, since account creation, least-privilege scopes, and
provider-specific gotchas (OAuth consent screen quirks, secret rotation,
IAM policies) are enough detail to warrant their own document:

- [docs/S3.md](S3.md) — Amazon S3 (static access keys, no OAuth)
- [docs/GOOGLE_DRIVE.md](GOOGLE_DRIVE.md) — Google Drive (OAuth)
- [docs/ONEDRIVE.md](ONEDRIVE.md) — Microsoft OneDrive (OAuth)

S3's credentials are static — "Save" is the whole connect flow. Google
Drive and OneDrive both need an OAuth consent step ("Connect with Google" /
"Connect with Microsoft") after saving credentials, redirecting to the
provider's own sign-in screen and back. Either way, once a card shows
**Connected**, head to the **Storage** tab to pick where its clips actually
go — the folder browser there can create, rename, and delete folders on
whichever backend you're browsing, local disk included.

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
