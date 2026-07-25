# Roadmap

The foundation lives on `master`. Everything below ships as a focused branch +
PR, run through CI, merged one at a time. Order optimizes for always-usable
increments.

## PR queue

Blink integration (account linking, 2FA, camera discovery, periodic sync) and
the clip pipeline (download tasks, ffmpeg thumbnails, Library grid with full
playback and bulk actions) have shipped.

1. **AI foundation** — frame extraction, analysis queue, `AIProvider`
   abstraction (OpenAI, Anthropic, Ollama local/cloud, Moondream local/cloud),
   provider settings UI with encrypted keys **and a "test connection" button**,
   two-tier escalation (cheap model first — the token-saving design carried
   over from the HA version), clip summaries + suspicion scores (`analyses`),
   `events`, re-analyze button, AI tab, `ai_usage` + AI Usage tab with cost
   charts. *Pauses for Brian's API keys.*
2. **Status & statistics** — camera health, sync history, storage metrics on
   the Status tab; worker job introspection.
3. **Rules & alerting** — rule engine, Discord/Slack webhooks, SMTP,
   quiet hours, alert history. Webhook URLs visible only in Settings; SMTP
   password masked with reveal toggle; all encrypted at rest.
4. **Local CV pipeline** — YOLO via ONNX Runtime with a **model-size setting**
   (nano/small/medium/large, or a better detector if benchmarks say so),
   ByteTrack tracking, per-camera baselines (`camera_baselines`),
   baseline-aware suspicion.
5. **Vehicles** — outline drawing UI, protected zones, monocular depth +
   ground-plane calibration, "within X feet" proximity alerts.
6. **Biometrics** — local face detection/embeddings (pgvector), enrollment
   from real frames with clustering + time-window mining, recognition events.
7. **Feedback learning** — correct/incorrect + suspicion reclassification +
   face false-positive/negative controls wired into galleries, thresholds,
   exemplar retrieval; accuracy trends on the AI tab.
8. **Product features** — archives + S3/Google Drive/OneDrive, live view
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
