# Blink AI Security

A self-hosted AI security platform for Blink cameras. Clips sync automatically
and flow through a two-tier vision-model pipeline — a cheap pass on every
clip, escalating to a stronger model only when something looks off — using
your choice of provider (OpenAI, Anthropic, Ollama, Moondream — local or
cloud). It produces plain-English summaries, suspicion scores, vehicle
proximity alerts (no depth sensor — geometry from the vehicle's own outline),
and local facial recognition that upgrades a clip's generic "a person" to an
enrolled household member's name. Every correction you give it — suspicion
verdicts, missed/wrong face matches — feeds back into per-camera baselines,
future prompts, and match behavior, so it gets better at *your* cameras and
*your* household specifically.

Built on [blinkpy](https://github.com/fronzbot/blinkpy) for Blink API access;
everything else — accounts, storage, AI, biometrics, events, alerts,
dashboards — is this application. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
for the overall design, [docs/BIOMETRICS.md](docs/BIOMETRICS.md) for facial
recognition specifically, and [docs/ROADMAP.md](docs/ROADMAP.md) for what
lands next.

## Facial recognition, and why it never phones home

Detection and embedding run locally via
[insightface](https://github.com/deepinsight/insightface) (SCRFD detection +
ArcFace recognition) over `onnxruntime`, in four selectable model tiers
trading speed for accuracy — pick a smaller one on a Raspberry Pi-class
host, a larger one where CPU/GPU headroom allows. Models install themselves
automatically (a one-time download from insightface's release assets the
first time a given tier is used, then cached on disk) — no manual setup step,
and Settings has a "verify / download now" action so you can force that
download immediately and confirm it worked, rather than finding out during
your next clip analysis.

**Biometric data — face crops, embeddings, and enrolled names — never
leaves this machine, and is never sent to any AI provider or cloud service,
under any configuration.** Recognition is deliberately decoupled from the
vision-language model call: the VLM always sees the same generic keyframes
and returns the same generic entity types whether biometrics is on or off.
Recognition runs afterward, locally, and only ever rewrites a label
in-place from something like "a person" to an enrolled name. Enabling it
does not change what leaves your network; disabling it (or AI analysis
entirely) does not break anything else — every layer is additive and
optional. See [docs/BIOMETRICS.md](docs/BIOMETRICS.md) for the full design,
including how corrections ("this wasn't them" / "you missed this face")
actually change future matching, not just relabel one clip.

## Live View and Security Feed

Blink doesn't offer a browser-playable live stream — its real liveview call
returns a raw `rtsps://` URL — so instead: **Live View** lets you pick a
camera (or two, side-by-side) and polls its latest snapshot on an interval,
with an on-demand forced refresh, save-clip, and full-resolution
screenshot-to-file. **Security Feed** is an at-a-glance dashboard grid of
your chosen cameras, each tile refreshing independently, that gets you as
close to "live" as Blink's motion-triggered stills allow — configurable
under Settings → Security Feed, with zero setup required beyond enabling
cameras. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#live-view--security-feed)
for how the passive/forced preview split keeps this free of Blink API abuse
and battery drain.

## Stack

FastAPI + SQLAlchemy 2 (async) + PostgreSQL 17/pgvector + Redis 8/arq on
Python 3.14 · Vue 3 + TypeScript + PrimeVue 4 + Vite · insightface/onnxruntime
for local facial recognition · Playwright for e2e · Chainguard-based
distroless production images, published for **both amd64 and arm64**.
Dependencies target latest-stable-compatible throughout; deliberate
exceptions (a dependency pinned below latest for a documented reason) are
tracked in [docs/ROADMAP.md](docs/ROADMAP.md#deferred--watching).

### Hardware

Runs comfortably on a small always-on box. Explicitly verified for arm64,
including a **Raspberry Pi 5 (8GB)** with an NVMe SSD over a PCIe HAT running
Ubuntu Server — a fast NVMe is worth it for the Postgres/clip-storage/model-
cache volumes, all of which see real disk I/O. `onnxruntime-gpu` ships no
arm64 wheels at all, so biometrics always runs on CPU there regardless of
the "Auto" compute setting; start with the smaller model tiers on a Pi-class
host (see [docs/BIOMETRICS.md](docs/BIOMETRICS.md#choosing-a-model-for-your-hardware)).
An x86_64 host with an NVIDIA GPU is auto-detected and used automatically.

## Quick start (production)

Requirements: Docker with the compose plugin (Linux, macOS, or Windows;
Ubuntu Server is a fully supported target).

```bash
make secrets        # generates values — paste them into .env
cp .env.example .env
make prod           # builds and starts everything: nginx, API, worker,
                     # Postgres/pgvector, Redis — with HTTPS on :443
```

First visit walks you through a short setup wizard: create your own admin
email/password (12 characters minimum — **there is no default username or
password to change**, `/api/setup` refuses to run a second time once an
account exists), optionally link your Blink account, and review the cameras
it finds before landing in the Library. AI analysis, vehicle protection, and
facial recognition all stay off until you turn them on in Settings — nothing
calls out to a third party until you configure a provider yourself.

`:80`/`:443` are the real defaults (override via `BLINK_HTTP_PORT`/
`BLINK_HTTPS_PORT` in `.env` if you need different ones) — internally nginx
listens on unprivileged 8080/8443 as a non-root user, which Docker maps back
to the standard ports, so dropping in your own certificate needs no port
number anywhere. TLS uses a generated self-signed certificate in
`docker/certs/` until you do; replace it any time (`cert.pem` + `key.pem`,
kept readable by the container: `chmod 644 docker/certs/*.pem`).

Production containers run non-root, with a read-only root filesystem,
`cap_drop: ALL`, and `no-new-privileges` — see
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#security-model) for the full
security model.

## Development

```bash
make dev            # hot-reloading stack: API :8000, frontend (Vite) :5173
```

The dev image carries the full toolchain (Vite, uv, hot reload); the
production image is built from scratch in a separate stage and never
installs any of it — see [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for how
the multi-stage builds are laid out.

## Testing & linting

```bash
make test           # backend (pytest, 100% coverage gate) + frontend (vitest)
make e2e             # build, seed, and run Playwright end to end, one command
make e2e-up          # just bring up the seeded e2e stack and leave it running
make e2e-test        # run Playwright again against an already-running e2e-up stack
make lint            # ruff · pyright · bandit · eslint · vue-tsc · hadolint
```

`make help` lists every command — one entry point each for production,
development, and testing, all built on the same images. More detail in
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## License

[MIT](LICENSE)
