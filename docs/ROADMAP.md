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
  screenshot-to-file. Nav sidebar collapses to give it more width.
- Security Feed: a dashboard grid of chosen (or every enabled) cameras, each
  tile polling independently, with admin-only Snap/Record actions per tile —
  the snapshot MVP called out below, not a stream.
- Settings → Live View and Settings → Security Feed hold each area's own
  config; Settings → General picks which of Library or Security Feed a
  fresh login lands on.

**Up next:**

1. **Rules engine** — today's alerting is one household-wide config (trigger
   toggles + thresholds); a real rule engine ("if unknown vehicle AND time
   between…") is more valuable now that biometrics and vehicle recognition
   give it more to key conditions on.
2. **Product features** — archives + S3/Google Drive/OneDrive,
   digests/notifications polish, search, timeline, backups.

## Deferred / watching

- **TypeScript 7**: adopt once vue-tsc supports the TS 7.1 stable API
  (~Oct 2026). Until then: latest 5.9.x.
- **PrimeVue 5**: released 2026-07; migrate in a dedicated PR once the v5
  ecosystem (themes, docs, blocks) settles.
- **redis-py 6+**: currently capped `<6` by arq; revisit when arq lifts it.
- **Live view streaming**: Blink's RTSPS liveview is the least stable surface
  of blinkpy, and returns a URL no browser can play directly regardless — the
  snapshot/on-demand-recording MVP (Live View, Security Feed) has shipped; a
  real streaming relay (WebRTC/HLS) remains a possible later addition, not
  started.
