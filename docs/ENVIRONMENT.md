# Environment variables

Everything the app itself reads is prefixed `BLINK_` (see
`backend/app/config.py`'s `Settings` class — the source of truth this table
is generated from). A few additional variables exist only for
`docker-compose.yml`'s own variable substitution (ports, database
passwords), not read by the application directly.

**Anything a user would reasonably want to change while running the app is
a Settings-page field instead**, not an environment variable — env vars
here are deployment-time/bootstrap concerns only: connection strings,
secrets, container filesystem paths, and observability. See the
[env-var-vs-settings audit](#why-arent-these-settings-fields) below for why
each one stays an env var rather than moving to the UI.

## Application (`BLINK_*`)

| Variable | Default | Purpose |
|---|---|---|
| `BLINK_ENVIRONMENT` | `development` | `development` \| `test` \| `production`. Production requires `BLINK_SECRET_KEY`/`BLINK_ENCRYPTION_KEY` to be set explicitly; the other two modes generate ephemeral ones so a bare checkout runs without a `.env` file. |
| `BLINK_DATABASE_URL` | (local dev default) | Async SQLAlchemy connection string, e.g. `postgresql+asyncpg://user:pass@host:5432/db`. |
| `BLINK_REDIS_URL` | (local dev default) | Redis connection string, used for the arq job queue and rate limiting. |
| `BLINK_SECRET_KEY` | *(required in production)* | Signs password-reset/verification tokens. Generate with `make secrets`. |
| `BLINK_ENCRYPTION_KEY` | *(required in production)* | Fernet key encrypting stored credentials (Blink account, SMTP, webhooks, cloud storage keys) at rest. Changing it makes previously stored credentials unreadable — there is no rotation flow today. |
| `BLINK_COOKIE_NAME` | `blink_session` | Session cookie name. |
| `BLINK_COOKIE_SECURE` | `true` | Marks the session cookie `Secure` (HTTPS-only). Only worth disabling behind a TLS-terminating proxy you fully trust. |
| `BLINK_SESSION_LIFETIME_SECONDS` | `604800` (7 days) | How long a login session stays valid. |
| `BLINK_STORAGE_DIR` | `/data/clips` | Default clip storage root inside the container. Overridable per-deployment from Settings → Storage (that override wins if set; this is the fallback). |
| `BLINK_BIOMETRICS_MODEL_CACHE_DIR` | `/data/insightface` | Where insightface's ONNX detection/recognition models are downloaded and cached on first use. |
| `BLINK_SYNC_INTERVAL_SECONDS` | `30` | How often the background worker syncs with Blink. Overridable from Settings → Blink sync (that override wins if set; this is the fallback). |
| `BLINK_INITIAL_SYNC_DAYS` | `1` | How many days of clip history to backfill the first time an account links. Overridable from Settings → Blink sync. |
| `BLINK_AUTO_ANALYZE_LIMIT` | `5` | Cap on how many clips a single sync run auto-queues for AI analysis, so a large backfill doesn't burn through AI budget unprompted. Overridable from Settings → Blink sync. |
| `BLINK_DISABLE_BLINK_NETWORK_CALLS` | `false` | Short-circuits every code path that makes a real call against Blink's cloud API (worker sync, preview refresh, record-clip). **Not a user-facing setting** — only ever set for the seeded e2e test stack, whose Blink account uses bogus credentials that can only ever fail a real call. |
| `BLINK_LOG_LEVEL` | `INFO` | Standard Python logging level. |
| `BLINK_LOG_JSON` | unset (auto) | Force JSON log output on/off. Unset defaults to JSON in production, human-readable elsewhere. |

## Compose-only (not `BLINK_`-prefixed, not read by the app itself)

These exist purely so `docker-compose.yml` can substitute them in; the
running application never reads them directly.

| Variable | Default | Purpose |
|---|---|---|
| `POSTGRES_PASSWORD` | *(required)* | Password for the `blink` Postgres role. Generate with `make secrets`. |
| `REDIS_PASSWORD` | *(required)* | Redis `requirepass` value. Generate with `make secrets`. |
| `BLINK_HTTP_PORT` | `80` | Host port nginx's plain-HTTP redirect listens on. |
| `BLINK_HTTPS_PORT` | `443` | Host port nginx's TLS listener listens on. |

## Why aren't these Settings fields?

Every variable above that a user might reasonably want to change while
running the app **already has** a Settings-page equivalent that overrides it
(storage location, Blink sync timing/backfill/analyze-limit) — the env var
is just the fallback default for a fresh deployment. The remaining
variables stay env-only because they're genuinely deployment-time or
security-bootstrap concerns, not runtime preferences:

- Connection strings and secrets (`DATABASE_URL`, `REDIS_URL`,
  `SECRET_KEY`, `ENCRYPTION_KEY`, the Postgres/Redis passwords) - the app
  needs these to even reach its own database/cache, so they can't
  themselves live *in* that database.
- Container filesystem paths tied to a specific volume mount
  (`BIOMETRICS_MODEL_CACHE_DIR`) - only meaningful relative to what's
  actually mounted into that specific container, decided at deploy time.
- Ports, cookie/session security flags, and log verbosity - ops-level
  concerns typically set once per deployment, not per-user preferences.
- `BLINK_DISABLE_BLINK_NETWORK_CALLS` - purely an e2e test-harness flag,
  never meant to be user-facing at all.
