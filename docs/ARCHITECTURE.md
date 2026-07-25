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

Live today: `users`, `access_tokens`.

Planned (added migration-per-feature; names locked so PRs stay consistent):

| Table | Purpose |
|---|---|
| `blink_accounts` | encrypted Blink credentials + token blob, last sync |
| `cameras` | Blink camera identity, name, enabled, per-camera settings JSONB |
| `clips` | media identity, storage path/backend, timestamps, status |
| `analyses` | AI summary text, suspicion score, provider/model, `is_current` (re-analysis keeps history; re-run only on explicit request) |
| `events` | typed detections (`PERSON_DETECTED`, `KNOWN_VEHICLE`, …) with confidence + metadata JSONB |
| `people` / `face_embeddings` | person registry; pgvector embeddings incl. negative examples, per-person threshold |
| `vehicles` / `vehicle_embeddings` | vehicle registry, per-camera outline polygons + allowed zones |
| `camera_baselines` | rolling per-camera activity statistics (hour-of-day object histograms, motion regions) |
| `feedback` | every correction: subject type/id, verdict, note, `applied` |
| `ai_usage` | per-call provider, model, tokens, cost, latency |
| `alert_channels` | discord/slack webhook + SMTP configs (secrets encrypted) |
| `rules` | rule engine conditions/actions JSONB, priority, enabled |

pgvector ships in the Postgres image from day one so embedding search needs no
image migration later.

## AI analysis pipeline

Two stages, cheap-first:

```
clip.mp4
  │  ffmpeg: keyframe extraction (scene-change + uniform sampling)
  ▼
Stage 1 — local perception (free, always on)
  │  YOLO object detection (ONNX Runtime — no torch in prod images)
  │  ByteTrack track association · zone tests · baseline deviation
  ▼  emits events + structured context
Stage 2 — VLM narration (token-metered, provider-abstracted)
  │  selected keyframes + stage-1 context → 1–2 sentence summary
  │  + structured suspicion assessment
  ▼
analyses row (cached forever; re-analyzed only via the button)
```

- **Stage 1** runs on every clip and produces `events` and detection context.
  ONNX Runtime keeps prod images torch-free and Python-3.14-friendly.
- **Stage 2** sends *keyframes + a text digest of stage-1 findings* to the
  configured provider. Two-tier escalation (cheap model first, stronger model
  when the cheap one flags uncertainty or suspicion) carries over from the
  Home Assistant version.
- **Providers**: OpenAI, Anthropic, Ollama (local), Ollama Cloud, Moondream
  (local), Moondream Cloud behind one `AIProvider` interface. Every call logs
  tokens/cost/latency to `ai_usage` (the AI Usage tab reads this).
- **Caching**: a clip's current analysis is immutable once stored. The
  re-analyze button supersedes (`is_current`) rather than overwrites, so
  accuracy history survives.

## Learning from feedback (not for show)

Every correction is stored in `feedback` and *must* change future behavior
through one of these mechanisms:

**Facial recognition** — embedding-gallery learning:
- "This is X" on a missed face → the face's embedding is enrolled into X's
  gallery (positives grow to cover angles/lighting).
- "This is not X" on a false match → stored as a *negative* embedding that
  vetoes matches near it.
- Per-person acceptance thresholds are recalibrated from the accumulated
  positive/negative sets (maximize separation), so every correction tightens
  that person's decision boundary. This is measurable, real improvement.

**Suspicion assessment** — three reinforcing loops:
1. **Per-camera baseline**: stationary cameras accumulate rolling statistics
   (what objects appear, when, where). Deviation from baseline feeds the
   suspicion score; "should not have been suspicious" feedback on routine
   activity accelerates baseline acceptance of that pattern.
2. **Exemplar retrieval**: clips get an embedding; corrected clips become
   labeled exemplars in pgvector. A new clip near "not suspicious" exemplars
   is damped, near "should have been flagged" exemplars is boosted (k-NN over
   the household's own history).
3. **Prompt conditioning**: the VLM prompt includes a compact digest of
   relevant past corrections ("the household marked deliveries like this
   non-suspicious"), retrieved via the same exemplar index.

The AI tab surfaces accuracy-over-time so the effect of feedback is visible.

## Vehicle protection & proximity

- The user draws a freeform outline around each vehicle per camera (canvas
  over a reference frame). Outlines define the protected region and anchor
  ground-plane calibration.
- **Distance estimation** on a single stationary camera: monocular depth
  (Depth Anything V2, ONNX) + a per-camera ground-plane calibration derived
  from the vehicle outline and person-height priors. A person's foot point
  projects to an estimated real-world distance from the vehicle.
- **Overlap vs. proximity**: depth ordering at the person/vehicle pixels
  distinguishes "walking behind the car in frame" from "standing at the car".
- Alert rule: "if anyone comes within X feet of <vehicle> [between HH:MM]".
  Estimates carry honest error bars (±, shown in the UI); calibration improves
  with a one-time guided step per camera.

## Biometrics enrollment from real frames

Enrollment uses *actual camera frames* (matching deployment conditions beats
studio photos): pick a window (24/48h/custom), the system mines detected faces
from clips in that window, clusters them by embedding similarity, and the user
labels whole clusters at once. Feedback keeps refining galleries afterwards.

**Privacy invariants (non-negotiable, carried from the original app):**
- Face embeddings and face crops never leave the machine — never sent to any
  cloud AI provider.
- A recognized person's *name* is never included in any provider-facing prompt.
- The suspicious-flag bypass for recognized people is all-or-nothing: it takes
  one approved face AND zero unrecognized faces anywhere in the clip.

## Rules & alerting

A rule engine separates detection from decisions:

```
IF   unknown_vehicle AND time BETWEEN 23:00 AND 06:00
THEN alert(discord, sms-style summary)
```

Channels: Discord webhook, Slack webhook, SMTP email — configs stored
encrypted; delivery via worker tasks with retry; quiet hours and dedup windows
built in. Later rules can reference recognition results ("ignore if vehicle is
registered").

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
