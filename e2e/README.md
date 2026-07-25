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

## Fixtures

The stack boots pre-seeded (see `backend/app/testing/seed.py`); known fixture
data is exported from `fixtures/index.ts`. Seeding is idempotent — add new
fixture records there as features grow.
