# Roadmap

The foundation lives on `master`. Everything below ships as a focused branch +
PR, run through CI, merged one at a time. Order optimizes for always-usable
increments.

## PR queue

Blink integration (account linking, 2FA, camera discovery, periodic sync),
the clip pipeline (download tasks, ffmpeg thumbnails, Library grid with full
playback and bulk actions), camera health/sync status, and RBAC (admin/viewer
roles) have shipped. First run is a 3-step wizard (admin account → link Blink
→ review discovered cameras, enable/disable any of them, and a nudge to set
up an AI provider) rather than just an account-creation form — see
[ARCHITECTURE.md](ARCHITECTURE.md#blink-integration) for the camera-identity
and auto-analysis-cap details behind it. Settings → Cameras' per-camera
enable/disable toggle gates AI analysis (and reanalyze/bulk-analyze) as well
as sync, not just the auto-analysis path. AI Settings has both a "test
connection" (reachability/auth only) and a "run test analysis" (a real,
tiny inference call proving the model name and response format actually
work) button per tier, for every provider including both Ollama variants.

**Shipped — AI analysis, vehicles, and alerts** (items 1, 3, and 5 from the
original plan below, landed together as one feature since they share a
pipeline and a Settings surface):
- `AIProvider` abstraction (OpenAI, Anthropic, Ollama local/cloud, Moondream
  local/cloud) with encrypted keys and a "test connection" button; two-tier
  escalation (cheap model first, stronger model only when the cheap one flags
  uncertainty/suspicion); clip summaries + suspicion scores (`analyses`),
  typed `events`, re-analyze / bulk-analyze, AI tab, `ai_usage` + AI Usage tab
  with token/cost charts.
- Camera baseline learning + few-shot prompt conditioning from corrections
  (see [ARCHITECTURE.md](ARCHITECTURE.md#learning-from-feedback-not-for-show)) —
  **not** the originally-planned separate local YOLO/ByteTrack CV stage; a
  capable VLM already returns typed detections directly, so a second model
  to bundle and keep accurate wasn't worth it at this scale. Revisit only if
  real-world accuracy demands it.
- Vehicle protection: outline drawing UI + comparable-triangles proximity
  estimation (see [ARCHITECTURE.md](ARCHITECTURE.md#vehicle-protection--proximity))
  — **not** the originally-planned monocular depth model + ground-plane
  calibration; geometry from the vehicle's own outline does the same job for
  a stationary camera without an extra model.
- Alerts: Discord/Slack webhooks, SMTP, quiet hours, dedup window, per-channel
  test send. Webhook URLs visible only in Settings; SMTP password masked with
  reveal toggle; all encrypted at rest. Not yet a general rule engine — see
  "Rules engine" below.
- Safety net: the initial Blink sync backfill is capped at 24h, and a sync
  that turns up a burst of new clips (first connect, or reconnecting after a
  while) only auto-queues the most recent few for analysis — see
  [ARCHITECTURE.md](ARCHITECTURE.md#keeping-a-fresh-connection-from-flooding-the-queue).

**Shipped — Biometrics** (local facial recognition; see
[docs/BIOMETRICS.md](BIOMETRICS.md) for the full design):
- insightface (SCRFD + ArcFace) local detection/embeddings, pgvector
  storage, four selectable model tiers trading speed for accuracy, CPU/GPU
  auto-selection with a correct arm64 (Raspberry Pi-class) fallback.
- Enrollment lives inline on the Biometrics tab (camera → time range,
  capped at 24h/48h/7 days → clip → frame → face → person), not a modal —
  **not** the originally-planned automatic clustering/time-window mining;
  a direct manual picker turned out to be the better fit once actually
  built. Full person CRUD (rename, delete, add/remove individual face
  samples) alongside it.
- Recognition is a local, post-hoc label rewrite after the VLM call — never
  a face, embedding, or name sent to any provider. A model-load failure
  (e.g. a flaky first-time download) degrades around, never discarding a
  VLM result that already succeeded.
- Feedback loop, from the clip modal: "report a missed face" enrolls a
  positive sample directly; "this wasn't them" on a wrong match stores a
  *negative* sample that vetoes future matches to that face pattern —
  **not** built: per-person threshold recalibration (one global threshold
  today).
- Library gets a recognized-person badge on clip thumbnails, a per-person
  filter, an "any recognized" toggle, and a live count stat.

**Shipped — Live View and Security Feed** (see
[ARCHITECTURE.md](ARCHITECTURE.md#live-view--security-feed) for the full
design):
- Live View: pick a camera (or two, side-by-side in compare mode), with
  auto-refresh, on-demand forced refresh, save-clip, and a full-resolution
  screenshot-to-file. Nav sidebar collapses to give it more width. An
  explicit per-camera "Start live view" button (never automatic) begins a
  real HLS stream — blinkpy's own local relay remuxed through ffmpeg — for
  any camera whose live-view session negotiates `immis://`; a camera that
  negotiates `rtsps://` instead shows a clear "not supported" message. The
  snapshot stays the default view either way.
- Security Feed: a dashboard grid of chosen (or every enabled) cameras, each
  tile polling independently, with admin-only Snap/Record actions per tile —
  snapshot-only, unaffected by Live View's streaming addition above.
- Settings → Live View and Settings → Security Feed hold each area's own
  config; Settings → General picks which of Library or Security Feed a
  fresh login lands on.

**Shipped — Cloud storage archiving & Integrations** (see
[docs/STORAGE.md](STORAGE.md) for the full design):
- Archive/restore a clip's video to Amazon S3, Google Drive, or Microsoft
  OneDrive — one canonical location at a time, never a cached second copy.
  S3 via `boto3` (SigV4-signed presigned download links); Google Drive and
  OneDrive via their official OAuth SDKs, with a self-issued encrypted
  bearer-token link standing in for a presigned URL (neither provider
  offers one without making the file public).
- A new top-level **Integrations** page: a searchable, category-filterable
  directory to connect each provider, with inline (never modal) per-provider
  config and a combined test-connection action.
- **Settings → Archived**: a single "where do new downloads end up"
  setting — left on local disk by default, or auto-archived to a connected
  provider right after a clip finishes analysis.
- **Not yet built**: browsing a connected provider's folder tree or
  creating folders from within the app (upload/download/delete only today).

**Up next:**

1. **Rules engine** — today's alerting is one household-wide config (trigger
   toggles + thresholds); a real rule engine ("if unknown vehicle AND time
   between…") is more valuable now that biometrics and vehicle recognition
   give it more to key conditions on.
2. **Product features** — a cloud-provider file browser/folder creation for
   the Storage tab, digests/notifications polish, search, timeline, backups.
3. **A fake Blink API server for e2e** — the e2e stack's seeded Blink account
   uses bogus credentials (there's no real account to give it), so anything
   that makes a genuine call against Blink's cloud — the worker's background
   sync, camera preview refresh, record-clip — is disabled in that
   environment via `Settings.disable_blink_network_calls`, and instead just
   serves the seeded cached fixtures (see `docs/STORAGE.md`-adjacent comments
   in `app/config.py`/`app/livefeed/service.py`). That's a deliberate,
   working short-circuit, not a mock — a real fake HTTP server standing in
   for Blink's API (matching blinkpy's actual request/response shapes) would
   let e2e exercise the genuine success-path code (a real sync discovering
   clips, a real forced snapshot) instead of always taking the
   cached/disabled branch. Worth doing if e2e ever needs to assert on that
   success path specifically; not needed for anything today.

## Deferred / watching

- **TypeScript 7**: adopt once vue-tsc supports the TS 7.1 stable API
  (~Oct 2026). Until then: latest 5.9.x.
- **PrimeVue 5**: released 2026-07; migrate in a dedicated PR once the v5
  ecosystem (themes, docs, blocks) settles.
- **redis-py 6+**: currently capped `<6` by arq; revisit when arq lifts it.
