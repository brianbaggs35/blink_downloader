# Biometrics: local facial recognition

Optional, off by default, and strictly additive: with it disabled the app
behaves exactly as it did before this feature existed — clips download,
catalogue, and get AI-analyzed (or not, if AI analysis itself is disabled)
with no change. Enabling it adds one thing only: a clip's already-generic
"a person" entity gets upgraded to an enrolled person's name, locally, after
the AI call has already happened.

**The non-negotiable constraint this whole design serves: biometric data
never leaves this machine.** Not to a cloud AI provider, not anywhere off
the local network. Everything below exists to make that true structurally,
not just by policy.

## How recognition fits around AI analysis, not into it

```
clip.mp4
  │  ffmpeg: keyframe extraction (same frames the VLM sees)
  ▼
VLM analysis (tier 1 [+ tier 2]) — generic entities: "a person", bbox, ...
  │  (this call already happened; biometrics has not run yet)
  ▼
biometrics enabled?
  │                      │
  no → done             yes → detect faces in the same keyframes locally
                                │  (insightface, on-box, no network call)
                                ▼
                          match each face against enrolled embeddings
                                │
                                ▼
                          face's bbox contained in a "person" entity's bbox?
                                │
                                ▼
                          rewrite that entity's label to the matched name,
                          in place, on the already-computed VLM result
```

The VLM never sees a face crop, an embedding, or a name — it only ever sees
the same keyframes and returns the same generic entity types it always has.
Recognition is a **local, post-hoc label rewrite** keyed on bounding-box
containment (`_upgrade_person_labels` / `_bbox_overlap_ratio` in
`app/ai/pipeline.py`) — not a symmetric IoU, since a face is naturally a
small fraction of a whole-body box; IoU would stay low even for a correct
match. A model-load failure (a flaky first-time download) or a decode error
during this step is caught and logged, never allowed to discard a VLM result
that already succeeded — see `ModelLoadError`/`RecognitionError` handling in
`run_analysis`.

## Models

Detection and embedding both come from
[insightface](https://github.com/deepinsight/insightface) via `onnxruntime`,
using one of its four named "buffalo" model packs — SCRFD for detection,
ArcFace (a 512-dim, L2-normalized embedding) for recognition, sharing the
same embedding space across all four packs so switching packs doesn't
invalidate previously-enrolled samples. Smallest/fastest to largest/most
accurate:

| Pack | Settings label | Tradeoff |
|---|---|---|
| `buffalo_sc` | Fastest (smallest) | Lowest accuracy; runs comfortably on low-power hosts (Raspberry Pi-class) |
| `buffalo_s` | Fast | Good balance for a modest CPU without much headroom |
| `buffalo_m` | Balanced | Recommended default for most systems |
| `buffalo_l` | Most accurate (largest) | Best accuracy, at the cost of more CPU/GPU work per clip |

**Installation is automatic, not a manual step**: the first time a given
pack is actually used, insightface downloads its ONNX weights from its
GitHub release assets into the configured cache directory
(`BLINK_BIOMETRICS_MODEL_CACHE_DIR`, an explicit Docker volume — both
backend/worker run with a read-only root filesystem in prod, so this is a
functional requirement, not a convenience) and reuses it from then on. A
cold download takes on the order of tens of seconds depending on connection
speed — this is the *only* time biometrics needs outbound internet access at
all; every inference call afterward is fully offline.

Rather than silently eating that delay during the next real clip analysis
(and risking a job timeout on a slow connection), **Settings > Biometrics**
has a "Verify / download model" button that forces the download immediately
and reports pass/fail with the resolved execution provider, so enabling the
feature gives an admin an immediate, clear signal instead of a surprise
later.

## Choosing a model for your hardware

- **`onnxruntime-gpu` ships no arm64 wheels at all** (x86_64/win_amd64 only)
  — so on a Raspberry Pi or other arm64 host, CPU is the only option
  regardless of the "Auto" setting, and `resolve_providers()` falls back to
  it correctly without any platform-specific branching in this codebase.
- **Raspberry Pi 5 (8GB) and similar low-power arm64 hosts**: start with
  `buffalo_sc` or `buffalo_s`. Move up only if recognition accuracy is
  insufficient for your household and the added per-clip latency (more
  compute per keyframe, on every analyzed clip with biometrics enabled) is
  acceptable for your clip volume.
- **A host with an NVIDIA GPU and the CUDA execution provider available**:
  "Auto" (the default) uses it automatically — `available_providers()` in
  Settings shows exactly what `onnxruntime` detects in this process, so you
  can confirm before relying on it.
- **A capable x86_64 CPU with no GPU**: `buffalo_m` or `buffalo_l` are
  reasonable at typical household clip volumes.

Detection input size is fixed at 640×640 (insightface's own documented
default for the SCRFD detector) — large enough for a security camera's wide
field of view without the extra cost of the next size up; not currently
exposed as a setting.

## Enrollment

Everything lives on the **Biometrics tab** — deliberately not a modal.
Picking a camera, a time range, a specific clip, and a frame is too much
interaction to manage well in a dialog, so the tab itself switches between
a people grid and a full-page detail view per person, rather than opening
dialogs on top of it.

1. **Add a person** (name only) or select an existing one from the grid.
2. Their detail view shows enrolled face samples (deletable individually)
   and an inline enrollment panel: pick a **camera**, a **time range**
   (24 hours / 48 hours / 7 days — capped there deliberately: an active
   household camera can turn up hundreds to thousands of clips beyond a
   week, which is a client-side list nobody can usefully scroll through),
   then a specific downloaded clip from that window.
3. Scrub the clip to a frame; detected faces are boxed live. Click one to
   select it, then enroll it — the frame is re-extracted and re-detected
   server-side rather than trusting anything the client echoes back (the
   clip file is the only source of truth for what gets embedded).
4. Repeat with more clips/frames for the same person — more samples across
   different angles, lighting, and times of day measurably improve match
   accuracy, since a face is matched against *every* enrolled sample and
   the closest one wins.

The same picker (extracted as `ClipFramePicker.vue`) also powers two
corrections reachable from a clip's own modal, so a household member
reviewing footage never has to leave it to fix a recognition mistake:

- **"Report a missed face"** — the pipeline didn't recognize someone; pick
  the frame and face, assign it to a person (existing or new). A direct
  positive-sample enrollment, identical to the Biometrics tab's flow.
- **A report icon on a recognized entity's tag** — the pipeline recognized
  the *wrong* person. This is the one destructive-feeling correction that's
  actually generative: it re-detects the clip's faces to find whichever one
  triggered the bad match, stores it as a **negative sample** for that
  person, deletes the recognition record, and reverts the label on the
  clip's stored analysis. `best_match()` then vetoes that person for any
  future face at least as close to the negative sample as to their best
  positive one — the report changes future matching immediately, not just
  this clip's history. (Per-person threshold *recalibration* from the
  accumulated positive/negative sets is not built — match confidence is one
  global setting, not tightened per person.)

## Never mark suspicious

Each enrolled person has a **"Never mark suspicious"** toggle (in their detail
panel on the Biometrics tab, admin-only). When on, any clip where that person
is recognized — regardless of what the VLM's raw suspicion score was — is
persisted with `suspicion_label = routine` instead of whatever
`suspicion_label_for()` would otherwise return. That, in turn, suppresses the
`suspicious_activity` Event and the push-alert dispatch for that clip, since
both are gated on the final label, not the raw score.

For a household member (or a frequent, known-safe visitor) this stops routine
comings-and-goings from tripping alerts just because a package on the porch
or an unusual hour pushed the model's score up. It's intentionally a
post-hoc override, not a pre-emptive skip: tier 2 escalation is decided
*before* face recognition runs (recognition needs the tier 1/2 result's
entities to label against), so a clip can still escalate to — and be billed
against — tier 2 even when the person who ends up bypassing the label was
recognized. `Analysis.suspicion_score` is left at its raw, unmodified value;
only the label (and what's gated on it) is overridden, so the score and label
can legitimately disagree on a bypassed clip.

## Settings

**Settings > Biometrics**, admin-only:

| Setting | Effect |
|---|---|
| Enabled | Master switch for automatic recognition during clip analysis. Enrollment/CRUD work regardless — this only gates the AI-pipeline integration. |
| Model | Which buffalo pack to use — see the table above. |
| Compute | Auto (GPU if `onnxruntime` reports one available, else CPU) or CPU-only. Shows what's actually detected on this server. |
| Match confidence threshold | Cosine-similarity cutoff for a positive match (0–1). Higher means fewer false matches but a harder time recognizing an unusual angle. |
| Verify / download model | Forces the configured pack to download and load right now, reporting pass/fail and the resolved provider. |

## Data and storage

- `people` / `face_embeddings` / `recognized_faces` / `biometrics_settings`
  — see [ARCHITECTURE.md](ARCHITECTURE.md#data-model) for the full schema.
- Face sample thumbnails and person profile thumbnails are written through
  the same `ClipStorage` abstraction clips use — local disk today, with the
  same future-archival seam.
- `face_embeddings.embedding` is a pgvector `Vector(512)` column — matching
  is currently done in plain Python over all enrolled samples (cheap at
  household scale: at most a few hundred rows), not a pgvector similarity
  query; revisit only if that stops being true.
