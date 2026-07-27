.DEFAULT_GOAL := help
SHELL := /bin/bash

COMPOSE_PROD := docker compose -f docker-compose.yml
COMPOSE_DEV  := docker compose -f docker-compose.dev.yml
COMPOSE_TEST := docker compose -f docker-compose.test.yml

.PHONY: help secrets certs prod prod-stop prod-logs prod-down dev dev-stop dev-logs dev-down \
	test test-db test-stop test-backend test-backend-fast test-frontend e2e e2e-up e2e-test e2e-down \
	lint lint-backend lint-frontend fmt migrate makemigration api-types \
	db-shell clean

help: ## Show this help
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

secrets: ## Generate values for .env (prints them; paste into .env)
	@echo "# Paste these into .env (see .env.example):"
	@echo "BLINK_SECRET_KEY=$$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
	@echo "BLINK_ENCRYPTION_KEY=$$(python3 -c 'import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')"
	@echo "POSTGRES_PASSWORD=$$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
	@echo "REDIS_PASSWORD=$$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"

certs: ## Generate a self-signed TLS certificate into docker/certs (replace with real ones any time)
	@mkdir -p docker/certs
	@test -f docker/certs/cert.pem || openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 \
		-days 825 -nodes -keyout docker/certs/key.pem -out docker/certs/cert.pem \
		-subj "/CN=blink.local" \
		-addext "subjectAltName=DNS:localhost,DNS:blink.local,IP:127.0.0.1"
	@# nginx runs as a non-root user in the container and must be able to read
	@# the mounted key. Applies to user-supplied certificates too.
	@chmod 644 docker/certs/cert.pem docker/certs/key.pem
	@echo "Certificates ready in docker/certs/"

prod: certs ## Start the production stack (requires .env — run `make secrets` first)
	@test -f .env || (echo "ERROR: .env missing. Run 'make secrets' and create .env from .env.example." && exit 1)
	$(COMPOSE_PROD) up -d --build

prod-stop: ## Stop production containers without removing them (resume with `make prod`)
	$(COMPOSE_PROD) stop

prod-logs: ## Tail production logs
	$(COMPOSE_PROD) logs -f

prod-down: ## Stop AND remove production containers (volumes/data are kept)
	$(COMPOSE_PROD) down

dev: ## Start the development stack with hot reload (API :8000, frontend :5173)
	$(COMPOSE_DEV) up -d --build
	@echo "Dev stack up: frontend http://localhost:5173 · API http://localhost:8000 · logs: make dev-logs"

dev-stop: ## Stop dev containers without removing them (resume with `make dev`)
	$(COMPOSE_DEV) stop

dev-logs: ## Tail development logs
	$(COMPOSE_DEV) logs -f

dev-down: ## Stop AND remove dev containers (volumes/data are kept)
	$(COMPOSE_DEV) down

test: test-backend test-frontend ## Run backend + frontend test suites

test-db: ## Start just the throwaway test Postgres/Redis (for local pytest runs)
	$(COMPOSE_TEST) up -d --wait postgres-test redis-test

test-stop: ## Stop test containers without removing them
	$(COMPOSE_TEST) stop

test-backend: ## Run backend tests in a container against throwaway Postgres/Redis
	$(COMPOSE_TEST) --profile unit run --rm --build backend-tests
	$(COMPOSE_TEST) --profile unit down

test-backend-fast: ## Run backend tests from the local venv (starts test db/redis)
	$(COMPOSE_TEST) up -d --wait postgres-test redis-test
	cd backend && uv run pytest

test-frontend: ## Run frontend unit tests with coverage
	cd frontend && npm run test

e2e: certs ## Build, seed, and run Playwright end to end in one shot (tears down after)
	@$(COMPOSE_TEST) --profile e2e down -v --remove-orphans 2>/dev/null || true
	$(COMPOSE_TEST) --profile e2e up --build --abort-on-container-exit --exit-code-from playwright; \
	status=$$?; $(COMPOSE_TEST) --profile e2e down -v; exit $$status

e2e-up: certs ## Bring up the seeded e2e stack and leave it running (for iterative test-writing)
	@$(COMPOSE_TEST) --profile e2e down -v --remove-orphans 2>/dev/null || true
	$(COMPOSE_TEST) --profile e2e up --build -d postgres redis backend worker frontend
	@echo "e2e stack up: https://localhost:8443 - run 'make e2e-test' to run Playwright, 'make e2e-down' when done"

e2e-test: ## Run Playwright against an already-running `make e2e-up` stack
	$(COMPOSE_TEST) --profile e2e run --rm playwright

e2e-down: ## Tear down the e2e stack
	$(COMPOSE_TEST) --profile e2e down -v

lint: lint-backend lint-frontend lint-e2e ## Run every linter

lint-backend: ## ruff + pyright + bandit
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run bandit -c pyproject.toml -r app -q

lint-frontend: ## eslint + vue-tsc
	cd frontend && npm run lint && npm run typecheck

lint-e2e: ## eslint + tsc for the Playwright suite
	cd e2e && npm run lint && npm run typecheck

fmt: ## Auto-format backend and frontend
	cd backend && uv run ruff check --fix . && uv run ruff format .
	cd frontend && npm run lint:fix
	cd e2e && npm run lint:fix

migrate: ## Apply database migrations (local dev database on :5432)
	cd backend && uv run alembic upgrade head

makemigration: ## Create a migration: make makemigration m="add cameras table"
	cd backend && uv run alembic revision --autogenerate -m "$(m)"

api-types: ## Regenerate the typed frontend API client from the backend OpenAPI schema
	cd backend && uv run python -c "import json; from app.main import app; open('openapi.json','w').write(json.dumps(app.openapi(), indent=2))"
	cd frontend && npm run api:types

db-shell: ## psql into the dev database
	$(COMPOSE_DEV) exec postgres psql -U blink blink

create-admin: ## Create (or reset) an admin account on the dev stack - prompts for email/password
	$(COMPOSE_DEV) exec backend uv run python -m app.cli create-admin

create-admin-prod: ## Create (or reset) an admin account on the prod stack - prompts for email/password
	$(COMPOSE_PROD) exec backend python -m app.cli create-admin

clean: ## Stop everything and remove volumes (DESTROYS local data)
	$(COMPOSE_PROD) down -v --remove-orphans 2>/dev/null || true
	$(COMPOSE_DEV) down -v --remove-orphans 2>/dev/null || true
	$(COMPOSE_TEST) --profile e2e --profile unit down -v --remove-orphans 2>/dev/null || true
