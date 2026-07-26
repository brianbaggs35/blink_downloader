# Architecture

Blink AI Security is a standalone, self-hosted AI security platform built on
[blinkpy](https://github.com/fronzbot/blinkpy). The application owns user
accounts, camera management, clip storage, AI processing, events, alerts,
dashboards, facial recognition, and vehicle protection; blinkpy owns Blink API
communication — nothing else leaks through that boundary.

## System overview

```
                      ┌────────────────────────────────────────────┐
  Browser ── HTTPS ──▶│ nginx (Chainguard, TLS, CSP, static SPA)   │
                      └────────────┬───────────────────────────────┘
                                   │ /api
                      ┌────────────▼───────────┐     ┌─────────────┐
                      │ FastAPI backend        │────▶│ PostgreSQL   │
                      │ (auth, REST, OpenAPI)  │     │ + pgvector   │
                      └────────────┬───────────┘     └─────────────┘
                                   │ enqueues              ▲
                      ┌────────────▼───────────┐           │
                      │ arq worker             │───────────┘
                      │ sync · download · AI   │────▶ Redis (queue, cache,
                      └────────────┬───────────┘          rate limits)
                                   │
                          ┌────────▼────────┐
                          │ BlinkService    │──▶ blinkpy ──▶ Blink cloud
                          └─────────────────┘
```

One Python package (`backend/app`) serves both the API and the worker — same
image, different command. This avoids the model/service duplication a separate
top-level `worker/` package would create.

## Resilience seams

Third-party dependencies with bus-factor risk are wrapped behind interfaces we
own:

- **`app/blink/`** — `BlinkService` protocol. blinkpy is imported nowhere else.
  If Blink changes their API or blinkpy stalls, one module changes.
- **`app/users/`** — fastapi-users (upstream is in maintenance mode) is fully
  contained here: models, manager, cookie/DB-strategy backend.

## Blink integration

Home Assistant's Blink integration used to absorb a lot of this transparently
via its config-entry/coordinator machinery; without that layer, this
application owns it directly:

- **Auth/session persistence**: `blinkpy`'s token blob (cookies + auth header,
  not the account password) is encrypted (`SecretBox`) and stored on the
  `BlinkAccount` row, refreshed on every successful sync. A worker/container
  restart reloads it rather than forcing a fresh login. A token that's gone
  stale (revoked, expired, password changed on Blink's side) surfaces as
  `BlinkAccount.status = error` with `last_error` set — visible in Settings →
  Blink Account and on the Status page — rather than failing silently forever.
- **Camera identity**: cameras are upserted keyed on `(blink_account_id,
  blink_camera_id)` — the stable numeric ID Blink assigns, not the
  display name — so renaming a camera in the Blink app updates the existing
  row (and everything hanging off its id: clips, AI history, enrolled faces)
  instead of orphaning it under a new one.
- **Known limitation**: Blink's media-changed feed (what `blinkpy` exposes for
  clip discovery) identifies each clip's camera by **display name only**, not
  by the stable camera ID used for camera identity above — a limitation of the
  upstream feed itself, not something this app can key around. Two cameras
  sharing an exact (case-insensitive) name *within the same Blink account*
  (realistic for a multi-property account with the same room names on both)
  will have their clips attributed to whichever of the two cameras the sync
  loop resolved last. Give cameras unique names in the Blink app to avoid this.
- **Per-camera enable/disable** (Settings → Cameras): disabling a camera stops
  its clips from being downloaded at all, and — independently, in case a job
  was already queued before the toggle flipped — analysis (`analyze_clip`)
  refuses to run against a disabled camera's clips even if asked to directly
  via reanalyze/bulk-analyze. The rest of the app works the same with one
  camera enabled as with ten.
- **First-sync backfill cap**: a fresh link backfills the last
  `BLINK_INITIAL_SYNC_DAYS` (default 1 day), and only the
  `BLINK_AUTO_ANALYZE_LIMIT` most recent clips from that backfill (default 5)
  are automatically queued for AI analysis — everything else still downloads
  and appears in the Library, just not auto-analyzed, so a busy first sync
  can't flood the analysis queue (and, if a paid provider is configured,
  run up a surprise bill) the moment an account is linked. Older, undiscovered
  clips beyond `blinkpy`'s own per-request page cap are fetched by requesting
  enough pages up front (`BlinkPyService._MEDIA_PAGE_STOP`) rather than
  silently truncating, which is `blinkpy`'s own out-of-the-box default.

## Security model

- **Auth**: Argon2id password hashing; HttpOnly/Secure/SameSite=Lax cookie
  holding a random token stored server-side (`access_tokens`) — sessions are
  revocable by row deletion. No JWT in the browser.
- **No open registration**: a first-run setup wizard creates the single admin;
  members are invited later by the admin.
- **Secrets at rest**: `SecretBox` (Fernet, key = `BLINK_ENCRYPTION_KEY`)
  encrypts Blink credentials, SMTP passwords, webhook URLs, and AI provider
  keys before they touch Postgres. Display rules: webhook URLs are decryptable
  and shown *only* inside Settings; SMTP passwords are write-only with a
  show-toggle; provider keys are masked.
- **Rate limiting**: Redis fixed-window per-IP on login/setup.
- **Transport**: nginx terminates TLS 1.2/1.3 with HSTS and a strict CSP;
  the API also sets its own security headers.
- **Containers**: Chainguard (Wolfi) distroless images, non-root, read-only
  root filesystems, `cap_drop: ALL`, `no-new-privileges`, no shell in prod
  images. Postgres/Redis are never published outside the compose network.

## Data model

Live today:

| Table | Purpose |
|---|---|
| `users` / `access_tokens` | household accounts (admin/viewer), revocable sessions |
| `blink_accounts` | encrypted Blink credentials + token blob, last sync, status |
| `cameras` | Blink camera identity, name, enabled, free-text `security_context` fed into every analysis prompt for that camera |
| `clips` | media identity, storage path/backend, timestamps, download status |
| `ai_settings` | singleton row: tier1/tier2 provider+model+encrypted key+base URL, keyframe count, escalation threshold, feedback-context count |
| `analyses` | per-clip result: summary, suspicion score/label, tier used, `escalated`, detected entities (JSONB), vehicle-proximity result (JSONB), `is_current` (re-analysis supersedes rather than overwrites, so accuracy history survives) |
| `events` | typed occurrences derived from an analysis (`person_detected`, `vehicle_proximity_breach`, …), one row per `(clip, event_type)` |
| `camera_baselines` | rolling per-camera hour-of-day × entity-type histogram — "what does this camera normally see right now" |
| `feedback` | every correction on an analysis: verdict (correct / false positive / false negative), optional note |
| `ai_usage` | per-call provider, model, tier, prompt/completion/total tokens, estimated cost, latency, success — the AI Usage tab reads this directly |
| `vehicles` | one protected vehicle per camera: outline polygon (normalized 0–1 points) over a captured reference frame, real-world length, alert distance, enabled |
| `proximity_events` | one row per proximity breach: distance + error margin, so the Vehicles tab and alerts don't re-derive history from `analyses` |
| `alert_settings` | singleton row: Discord/Slack webhook (encrypted) + SMTP (encrypted password) config, trigger toggles/thresholds, quiet hours, dedup window |
| `people` | an enrolled household member or known visitor: name, profile thumbnail |
| `face_embeddings` | one enrolled face sample (pgvector, 512-dim ArcFace): source clip/frame provenance, `is_negative` for a confirmed-wrong-match sample that vetoes future matches to that face pattern |
| `recognized_faces` | one "this person appears in this clip" record per (clip, person), upserted on (re-)analysis |
| `biometrics_settings` | singleton row: enabled, insightface model pack, CPU/GPU execution preference, match-confidence threshold |

pgvector ships in the Postgres image from day one, used by both
`ai`-side embedding-adjacent features and biometrics.

## AI analysis pipeline

Two *tiers* of the same kind of model (a vision-language model), cheap-first —
not a local object detector feeding a VLM. A dedicated local CV stage (YOLO,
track association) was considered and deliberately dropped: it's another
model to bundle, version, and keep accurate, for a household-scale workload
where a capable VLM already returns typed detections directly.

```
clip.mp4
  │  ffmpeg: keyframe extraction (N evenly-spaced frames, default 4)
  ▼
Tier 1 — first pass (every downloaded clip that's queued for analysis)
  │  keyframes + camera's security_context + baseline digest
  │  + recent household corrections for this camera (few-shot)
  │  → summary, suspicion score/label, typed entities (structured output)
  ▼
score ≥ tier2_suspicion_threshold (default 0.5)?
  │                                   │
  no → done                          yes → Tier 2 — escalation
                                            │  same keyframes + tier-1's own
                                            │  summary/score, to a stronger
                                            │  model — refines rather than
                                            │  starts blind
                                            ▼
                                      analyses row (escalated=true)
```

- **Providers**: OpenAI, Anthropic, Ollama (local), Ollama Cloud, Moondream
  (local), Moondream Cloud — one `AIProvider` interface, tier 1 and tier 2
  configured independently (e.g. Moondream local for tier 1, Anthropic for
  tier 2). OpenAI/Anthropic/Ollama use native structured output; Moondream's
  API has no such mode, so its provider prompts for parseable JSON text and
  degrades honestly (routine, zero entities, a summary noting the parse
  failure) rather than pretending feature parity it doesn't have. "Local" and
  "cloud" variants of Ollama/Moondream are the same wire protocol at a
  different base URL, never a different code path.
- **Context, not just pixels**: every prompt includes the camera's
  admin-set `security_context` ("watches the driveway; a silver sedan is
  normally parked here overnight"), a digest of what that camera normally
  sees at this hour (see baselines, below), and the household's own recent
  corrections for that camera — a general-purpose VLM narrows to *this*
  household's definition of normal without any fine-tuning.
- **Every call is metered**: provider, model, tier, prompt/completion/total
  tokens, estimated cost, latency, and success are logged to `ai_usage`
  regardless of outcome — the AI Usage tab reads this directly, and a failed
  call (bad key, timeout, malformed response) is visible there rather than
  silently disappearing.
- **Caching**: a clip's current analysis is immutable once stored. Analyze
  again (Analyze now / Re-analyze / bulk-analyze) supersedes it (`is_current`
  flips) rather than overwriting, so accuracy history survives.
- **Vehicle proximity rides the same pass**: when a camera has an enabled
  vehicle outline, tier 1 and tier 2 both additionally ask for person
  bounding boxes, and the pipeline runs the geometry below against the first
  keyframe — no separate analysis pass, no separate API call.

### Keeping a fresh connection from flooding the queue

A first-time Blink link, or a reconnect after the household's network was
down for a while, can turn up dozens of clips in one sync — backfilling and
auto-analyzing all of them would burn through AI budget and rate limits on a
backlog nobody asked to see analyzed the moment they reconnected:

- **The initial backfill window is capped at 24 hours** (`BLINK_INITIAL_SYNC_DAYS`,
  default `1`) — a sync with no prior `last_sync` (first link, or first sync
  after being disconnected long enough that `last_sync` predates this) only
  looks back one day, not further into Blink's history.
- **Auto-analysis is capped per sync, not per clip**: if one sync run
  discovers more than `BLINK_AUTO_ANALYZE_LIMIT` (default `5`) new clips,
  only the most recent N (by recording time) are auto-queued for analysis.
  The rest still download normally — they're in the Library, playable,
  downloadable — they just aren't auto-analyzed. A routine sync (the normal
  steady state, a handful of clips at most) is never affected by this cap
  since it's already under the limit; every new clip going forward keeps
  getting analyzed automatically as before.
- **Nothing is left behind**: older clips in an oversized batch are one click
  away via "Analyze now" / "Re-analyze" in the clip modal, or select-many +
  Analyze in the Library's bulk actions — both bypass the cap entirely by
  design, since they're an explicit, deliberate request for that specific
  clip (or clips), not an automatic bulk trigger.

## Learning from feedback (not for show)

Every correction is stored in `feedback` and *must* change future behavior
through one of these mechanisms:

**Facial recognition** — embedding-gallery learning, from the clip modal:
- "Report a missed face" on a clip → picks a frame, re-detects, and enrolls
  the chosen face as a new positive sample for the chosen (or newly created)
  person — the same enrollment path as the Biometrics tab, just entered from
  a specific clip instead of a camera/time-range search.
- "This wasn't them" on a wrongly-recognized entity → re-detects the clip's
  faces, stores whichever one matched as a *negative* sample for that
  person, deletes the `recognized_faces` row, and reverts that entity's
  label on the stored analysis. `best_match()` then vetoes that person for
  any future face at least as close to the negative sample as to their best
  positive one — a report changes matching behavior immediately, not just
  this one clip's history.
- Not built: per-person threshold recalibration. Match confidence is one
  global `biometrics_settings.recognition_threshold`, not tightened
  per-person from the accumulated positive/negative sets — revisit if
  households with many enrolled people find the shared threshold too coarse.

**Suspicion assessment** — two reinforcing loops, live today:
1. **Per-camera baseline**: every analysis (suspicious or not) bumps an
   hour-of-day × entity-type histogram for that camera — a rolling, passive
   "what does this camera normally see right now." A **false-positive**
   correction ("this routine thing was wrongly flagged suspicious") bumps the
   same histogram at 3× the weight of a passive observation, so the
   household's correction visibly moves the baseline rather than waiting to
   be outweighed by future recurrences. The current hour's top entities are
   summarized into a one-line digest and included in every prompt for that
   camera.
2. **Few-shot prompt conditioning**: a camera's most recent corrections
   (false positives and false negatives, not confirmed-correct calls — those
   have nothing new to teach) are pulled in as short text examples in the
   prompt: *"Flagged suspicious, but was actually routine: …"* /
   *"Not flagged, but should have been considered suspicious: …"* The count
   is configurable (`feedback_context_count`, default 5, 0 disables it).

A third loop — pgvector k-NN exemplar retrieval over embedded clips — is
deliberately not built: at one household's realistic feedback volume (dozens
to low hundreds of corrections, not millions), an embedding index is real
infrastructure to bundle and maintain for marginal benefit over "the
household's own recent corrections for this camera," which the loop above
already gives the model. Revisit if usage patterns show it's worth it.

The AI tab surfaces suspicion breakdown and feedback accuracy so the effect
of correcting the system is visible, not just asserted.

## Vehicle protection & proximity

Pure geometry, no ML model — deliberately, not as a stopgap. A monocular
depth model (Depth Anything V2 or similar) was the obvious alternative and
was rejected: it's a heavy dependency to bundle and run on every analyzed
frame (unfriendly to a Raspberry Pi-class host), it's one more thing to keep
accurate across ONNX runtime/opset changes, and for a *stationary* camera —
already an assumption this whole feature leans on — comparable-triangles
reasoning gets the same practical answer from math alone, fully unit-testable
with hand-computed pixel coordinates instead of golden-image regression tests.

- **Setup**: capture a reference frame from the camera's most recent
  downloaded clip, then draw a polygon outline around the vehicle in it
  (click to add a point, click a point to remove) and enter its real-world
  length. This is the one manual step per camera; everything after is
  automatic.
- **The core idea**: a pinhole camera projects an object of real height `H`
  at distance `Z` to pixel height `h = f·H/Z` for some fixed, unknown focal
  length `f`. The vehicle's own outline plus its real-world length gives a
  local pixels-per-foot scale *at the vehicle's distance* — no camera
  calibration, no focal length lookup, no depth sensor.
- **Depth plausibility filter**: before asking "how many feet away,
  laterally," a detected person's apparent bounding-box height is compared
  against what an average adult (5.6 ft) would measure at the vehicle's
  depth, within a tolerance. This is what separates "standing at the car"
  from "walking on the sidewalk far behind it in the same part of the
  frame" — the classic monocular ambiguity — without needing true depth.
  A person who fails the plausibility check contributes no proximity
  estimate at all, rather than a wrong one.
- **Distance**: for a person who passes the filter, the shortest distance
  from their estimated foot point to the vehicle's outline polygon, in the
  local pixels-per-foot scale, is the estimate. Closest person wins when
  several are detected. Estimates carry an honest ± error margin (shown in
  the UI, not hidden), rather than a false-precision single number.
- **Alerting**: "someone came within `distance_threshold_feet` of the
  vehicle" is one of two alert triggers (alongside "clip scored suspicious"),
  with its own toggle, quiet hours, and dedup window — see Alerting, below.

This only makes sense for a camera that doesn't move (a mounted driveway/
porch camera, not a battery unit someone carries around) — the reference
frame and its calibration are only valid for the position they were captured
at.

## Biometrics: local face recognition

See [docs/BIOMETRICS.md](BIOMETRICS.md) for the full design — models, tiers,
settings, and hardware guidance. Summary:

Enrollment uses *actual camera frames* (matching deployment conditions beats
studio photos), entirely inline on the Biometrics tab rather than a modal
wizard — picking a camera and clip is too much to manage in a dialog. The
flow: pick a camera → a time range capped at 24h/48h/7 days (an active
household camera can turn up hundreds of clips beyond that, which nobody
can usefully browse) → a specific downloaded clip → scrub to a frame → click
a detected face → assign it to a new or existing person. Each enrolled
person's detail view embeds the same picker so adding more samples (more
angles, lighting, times of day — every sample improves matching) never
requires leaving their page. The clip modal offers the same underlying
picker for two corrections without leaving a clip you're already reviewing:
enrolling a face the pipeline missed, and reporting one it matched wrongly
(see Learning from feedback, above).

Detection/embedding is [insightface](https://github.com/deepinsight/insightface)
(SCRFD detector + ArcFace recognition head) via onnxruntime, auto-selecting
CUDA when `onnxruntime` reports it available and falling back to CPU
otherwise (`onnxruntime-gpu` has no arm64 wheels at all, so this also keeps
a Raspberry Pi-class host correct without any platform branching). Settings
exposes the model pack (buffalo_sc/s/m/l, smallest-fastest to
largest-most-accurate) and match-confidence threshold.

**Privacy invariants (non-negotiable):**
- Face embeddings and face crops never leave the machine — never sent to any
  cloud AI provider, never leave the local network.
- A recognized person's *name* is never included in any provider-facing
  prompt — the VLM call happens first, on generic keyframes, exactly as it
  would with biometrics disabled entirely; recognition only rewrites a
  "person" entity's label to the matched name afterward, locally, by
  correlating bounding boxes (see `_upgrade_person_labels` /
  `_bbox_overlap_ratio` in `app/ai/pipeline.py`).
- Biometrics is strictly additive and optional: disabled, or a model-load
  failure mid-analysis (e.g. a flaky first-time download), never blocks or
  degrades the VLM analysis itself — only the recognized-name upgrade is
  skipped for that pass.

## Alerting

One household-wide config today (`alert_settings`), not yet a general rule
engine ("if unknown vehicle AND time between…" conditions are a natural next
step once facial/vehicle recognition gives more to key rules on):

- **Channels**: Discord webhook, Slack webhook, SMTP email — each
  independently enabled, webhook URLs and the SMTP password encrypted at
  rest. Delivery is a dedicated worker job, decoupled from analysis: a slow
  or misconfigured alert channel never blocks or delays the analysis that
  triggered it. Each configured channel is tried independently per alert, so
  one channel failing doesn't suppress the others.
- **Triggers**: a clip scored suspicious (own threshold, independent of the
  tier-2 escalation threshold) and/or someone breaching a protected vehicle's
  distance — each with its own on/off toggle.
- **Quiet hours**: a start/end time (wraps midnight correctly, e.g.
  22:00–06:00) during which alerts are silently skipped, not queued for
  later delivery.
- **Dedup**: a Redis `SET NX` with a TTL of `dedup_window_minutes` keyed on
  camera + reason suppresses repeat alerts for the same situation within the
  window, rather than a database table — it's ephemeral state by nature, and
  the worker heartbeat already uses Redis the same way.
- **Settings > Alerts** includes a "send test alert" that exercises every
  configured, enabled channel against the currently *saved* settings and
  reports per-channel success/failure, so a webhook typo surfaces before
  it's relied on at 2am.

## Storage

`clips` rows carry `storage_backend` + `storage_path` behind a storage
interface: local disk now; S3, Google Drive, and OneDrive adapters later for
archives. Archival moves bytes and flips the backend field — the Library and
Storage tabs read the same rows throughout.

## Environments

| | entry point | images | notes |
|---|---|---|---|
| prod | `make prod` | Chainguard distroless | TLS, read-only FS, healthchecks |
| dev | `make dev` | python:3.14-slim / node:24 | hot reload both sides |
| test | `make test-backend` / `make e2e` | throwaway + prod-like | e2e stack is seeded via `app/testing/seed.py` |
