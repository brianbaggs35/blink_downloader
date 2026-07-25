# Roadmap

The foundation lives on `master`. Everything below ships as a focused branch +
PR, run through CI, merged one at a time. Order optimizes for always-usable
increments.

## PR queue

Blink integration (account linking, 2FA, camera discovery, periodic sync),
the clip pipeline (download tasks, ffmpeg thumbnails, Library grid with full
playback and bulk actions), camera health/sync status, and RBAC (admin/viewer
roles) have shipped.

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

**Up next:**

1. **Biometrics** — local face detection/embeddings (pgvector), enrollment
   from real frames with clustering + time-window mining, recognition events,
   embedding-gallery learning from corrections (positive/negative examples,
   per-person thresholds). Face data never leaves the machine; a recognized
   person's name never reaches a cloud AI provider.
2. **Rules engine** — today's alerting is one household-wide config (trigger
   toggles + thresholds); a real rule engine ("if unknown vehicle AND time
   between…") is more valuable once biometrics and vehicle recognition give
   it more to key conditions on.
3. **Product features** — archives + S3/Google Drive/OneDrive, live view
   (snapshot/short-capture MVP, then stream relay), digests/notifications
   polish, search, timeline, backups.

## Deferred / watching

- **TypeScript 7**: adopt once vue-tsc supports the TS 7.1 stable API
  (~Oct 2026). Until then: latest 5.9.x.
- **PrimeVue 5**: released 2026-07; migrate in a dedicated PR once the v5
  ecosystem (themes, docs, blocks) settles.
- **redis-py 6+**: currently capped `<6` by arq; revisit when arq lifts it.
- **Live view streaming**: Blink's RTSPS liveview is the least stable surface
  of blinkpy — MVP is snapshot + short recordings saved to the Library, real
  streaming (WebRTC/HLS relay) afterwards.
