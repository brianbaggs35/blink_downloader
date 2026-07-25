# Blink AI Security

A self-hosted AI security platform for Blink cameras. Clips sync automatically
and flow through a two-stage AI pipeline — local computer vision plus your
choice of vision model (OpenAI, Anthropic, Ollama, Moondream — local or cloud)
— producing summaries, suspicion assessments, facial recognition, and vehicle
protection with proximity alerts. Your feedback actively retrains the system's
thresholds. Face data never leaves your machine.

Built on [blinkpy](https://github.com/fronzbot/blinkpy) for Blink API access;
everything else — accounts, storage, AI, events, alerts, dashboards — is this
application. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the design
and [docs/ROADMAP.md](docs/ROADMAP.md) for what lands next.

## Stack

FastAPI + SQLAlchemy 2 (async) + PostgreSQL/pgvector + Redis/arq on
Python 3.14 · Vue 3 + TypeScript + PrimeVue 4 + Vite · Playwright ·
Chainguard-based distroless production images (amd64 + arm64).

## Quick start (production)

Requirements: Docker with the compose plugin.

```bash
make secrets        # generates values — paste them into .env
cp .env.example .env
make prod           # builds and starts everything with HTTPS on :443
```

First visit walks you through creating the admin account. TLS uses a generated
self-signed certificate in `docker/certs/` — drop real ones there any time
(`cert.pem` + `key.pem`, and keep them readable by the container:
`chmod 644 docker/certs/*.pem`).

## Development

```bash
make dev            # hot-reloading stack: API :8000, frontend :5173
```

## Testing & linting

```bash
make test           # backend (pytest, 100% coverage gate) + frontend (vitest)
make e2e            # Playwright against a production-like seeded stack
make lint           # ruff · pyright · bandit · eslint · vue-tsc
```

`make help` lists every command. More detail in
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## License

[MIT](LICENSE)
