# End-to-end tests

Playwright specs that run against a **production-like stack** (prod container
images, nginx TLS, seeded Postgres) — not the dev server.

## Running

```bash
make e2e
```

That builds the stack from `docker-compose.test.yml` (profile `e2e`), waits for
the backend to be healthy (migrations + fixture seeding happen in-container),
runs Playwright from the official image, and tears everything down.

To iterate locally against an already-running stack:

```bash
cd e2e
npm install
E2E_BASE_URL=https://localhost:8443 npx playwright test
```

## Coverage

```bash
make e2e-coverage
```

Rebuilds the frontend with `VITE_COVERAGE=true` (instruments `src/**` via
`vite-plugin-istanbul` — never the default `npm run build`, so the real
production image is always the plain, uninstrumented one), runs the full
suite against it, and reports how much of the app the suite actually
exercised: a text summary in the terminal plus an HTML report at
`e2e/coverage/index.html`. Each test drains `window.__coverage__` after it
runs (see the `context` fixture in `fixtures/index.ts`) to
`e2e/.nyc_output/`, which `nyc` then merges and reports on.

This is a different signal from `make e2e`'s pass/fail: coverage measures
*how much of the app's code* the suite reaches, not whether behavior is
correct. Both matter; only this target costs the extra instrumented rebuild.

## Fixtures

The stack boots pre-seeded (see `backend/app/testing/seed.py`); known fixture
data is exported from `fixtures/index.ts`. Seeding is idempotent — add new
fixture records there as features grow.
