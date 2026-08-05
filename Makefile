.DEFAULT_GOAL := help
SHELL := /bin/bash

COMPOSE_PROD     := docker compose -f docker-compose.yml
COMPOSE_PROD_GPU := $(COMPOSE_PROD) -f docker-compose.prod.gpu.yml
COMPOSE_DEV      := docker compose -f docker-compose.dev.yml
COMPOSE_DEV_GPU  := $(COMPOSE_DEV) -f docker-compose.gpu.yml
COMPOSE_TEST     := docker compose -f docker-compose.test.yml
COMPOSE_ONBOARDING := docker compose -f docker-compose.onboarding.yml

.PHONY: help secrets certs prod prod-start prod-gpu prod-gpu-start prod-stop prod-logs prod-down \
	dev dev-start dev-gpu dev-gpu-start dev-stop dev-logs dev-down \
	test test-db test-stop test-backend test-backend-fast test-frontend \
	e2e e2e-up e2e-up-start e2e-test e2e-down \
	e2e-onboarding e2e-onboarding-up e2e-onboarding-test e2e-onboarding-down \
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

prod: certs ## Start the production stack, always (re)building images first (requires .env — run `make secrets` first)
	@test -f .env || (echo "ERROR: .env missing. Run 'make secrets' and create .env from .env.example." && exit 1)
	$(COMPOSE_PROD) up -d --build

prod-start: certs ## Start prod using whatever's already built - no rebuild (use `make prod` after code changes)
	@test -f .env || (echo "ERROR: .env missing. Run 'make secrets' and create .env from .env.example." && exit 1)
	$(COMPOSE_PROD) up -d

prod-gpu: certs ## Start prod (GPU) always (re)building images first (requires nvidia-container-toolkit - see docs/BIOMETRICS.md)
	@test -f .env || (echo "ERROR: .env missing. Run 'make secrets' and create .env from .env.example." && exit 1)
	$(COMPOSE_PROD_GPU) up -d --build

prod-gpu-start: certs ## Start prod (GPU) using whatever's already built - no rebuild
	@test -f .env || (echo "ERROR: .env missing. Run 'make secrets' and create .env from .env.example." && exit 1)
	$(COMPOSE_PROD_GPU) up -d

prod-stop: ## Stop production containers without removing them (resume with `make prod`)
	$(COMPOSE_PROD) stop

prod-logs: ## Tail production logs
	$(COMPOSE_PROD) logs -f

prod-down: ## Stop AND remove production containers (volumes/data are kept)
	$(COMPOSE_PROD) down

dev: ## Start the dev stack with hot reload, always (re)building images first (API :8000, frontend :5173)
	$(COMPOSE_DEV) up -d --build
	@echo "Dev stack up: frontend http://localhost:5173 · API http://localhost:8000 · logs: make dev-logs"

dev-start: ## Start dev using whatever's already built - no rebuild (use `make dev` after dependency changes)
	$(COMPOSE_DEV) up -d
	@echo "Dev stack up: frontend http://localhost:5173 · API http://localhost:8000 · logs: make dev-logs"

dev-gpu: ## Start dev (GPU) always (re)building images first (requires nvidia-container-toolkit - see docs/BIOMETRICS.md)
	$(COMPOSE_DEV_GPU) up -d --build
	@echo "Dev stack up (GPU): frontend http://localhost:5173 · API http://localhost:8000 · logs: make dev-logs"

dev-gpu-start: ## Start dev (GPU) using whatever's already built - no rebuild
	$(COMPOSE_DEV_GPU) up -d
	@echo "Dev stack up (GPU): frontend http://localhost:5173 · API http://localhost:8000 · logs: make dev-logs"

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
	$(COMPOSE_TEST) --profile e2e up --build -d postgres redis backend worker frontend
	$(COMPOSE_TEST) --profile e2e run --rm --no-deps playwright; \
	status=$$?; \
	if [ "$$status" -ne 0 ]; then $(COMPOSE_TEST) --profile e2e logs postgres redis backend worker frontend; fi; \
	$(COMPOSE_TEST) --profile e2e down -v; exit $$status

e2e-up: certs ## Bring up the seeded e2e stack and leave it running, always (re)building images first
	@$(COMPOSE_TEST) --profile e2e down -v --remove-orphans 2>/dev/null || true
	$(COMPOSE_TEST) --profile e2e up --build -d postgres redis backend worker frontend
	@echo "e2e stack up: https://localhost:8443 - run 'make e2e-test' to run Playwright, 'make e2e-down' when done"

e2e-up-start: certs ## Bring up the seeded e2e stack using whatever's already built - no rebuild
	@$(COMPOSE_TEST) --profile e2e down -v --remove-orphans 2>/dev/null || true
	$(COMPOSE_TEST) --profile e2e up -d postgres redis backend worker frontend
	@echo "e2e stack up: https://localhost:8443 - run 'make e2e-test' to run Playwright, 'make e2e-down' when done"

e2e-test: ## Run Playwright against an already-running `make e2e-up` stack
	$(COMPOSE_TEST) --profile e2e run --rm --no-deps playwright

e2e-down: ## Tear down the e2e stack
	$(COMPOSE_TEST) --profile e2e down -v

e2e-onboarding: certs ## Build, boot an unseeded stack, and run the onboarding wizard suite end to end (tears down after)
	@$(COMPOSE_ONBOARDING) down -v --remove-orphans 2>/dev/null || true
	$(COMPOSE_ONBOARDING) up --build -d postgres redis backend worker frontend
	$(COMPOSE_ONBOARDING) run --rm --no-deps playwright; \
	status=$$?; \
	if [ "$$status" -ne 0 ]; then $(COMPOSE_ONBOARDING) logs postgres redis backend worker frontend; fi; \
	$(COMPOSE_ONBOARDING) down -v; exit $$status

e2e-onboarding-up: certs ## Bring up the unseeded onboarding stack and leave it running, always (re)building images first
	@$(COMPOSE_ONBOARDING) down -v --remove-orphans 2>/dev/null || true
	$(COMPOSE_ONBOARDING) up --build -d postgres redis backend worker frontend
	@echo "onboarding stack up: https://localhost:8444 - run 'make e2e-onboarding-test' to run Playwright, 'make e2e-onboarding-down' when done"

e2e-onboarding-test: ## Run the onboarding Playwright suite against an already-running `make e2e-onboarding-up` stack
	$(COMPOSE_ONBOARDING) run --rm --no-deps playwright

e2e-onboarding-down: ## Tear down the onboarding stack
	$(COMPOSE_ONBOARDING) down -v

e2e-coverage: certs ## Run e2e against an istanbul-instrumented frontend and report code coverage
	@$(COMPOSE_TEST) --profile e2e down -v --remove-orphans 2>/dev/null || true
	@rm -rf e2e/.nyc_output e2e/coverage
	VITE_COVERAGE=true $(COMPOSE_TEST) --profile e2e up --build -d postgres redis backend worker frontend; \
	VITE_COVERAGE=true COVERAGE_DIR=/e2e/.nyc_output $(COMPOSE_TEST) --profile e2e run --rm --no-deps playwright; \
	test_status=$$?; \
	if [ "$$test_status" -ne 0 ]; then \
	  exit "$$test_status"; \
	fi; \
	docker run --rm -v "$(CURDIR)/e2e:/e2e" alpine sh -c \
	  "chown -R $(shell id -u):$(shell id -g) /e2e/.nyc_output && rm -rf /e2e/node_modules"; \
	docker run --rm -v "$(CURDIR)/e2e:/e2e" -v "$(CURDIR)/frontend/src:/app/src:ro" -w /e2e \
	  --user "$(shell id -u):$(shell id -g)" -e npm_config_cache=/tmp/.npm-cache \
	  node:24-slim sh -c "npm ci --no-audit --no-fund && npm run coverage:report"; \
	report_status=$$?; \
	$(COMPOSE_TEST) --profile e2e down -v; \
	exit "$$report_status"

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
	$(COMPOSE_PROD) exec app python -m app.cli create-admin

clean: ## Stop everything and remove volumes (DESTROYS local data)
	$(COMPOSE_PROD) down -v --remove-orphans 2>/dev/null || true
	$(COMPOSE_DEV) down -v --remove-orphans 2>/dev/null || true
	$(COMPOSE_TEST) --profile e2e --profile unit down -v --remove-orphans 2>/dev/null || true
	$(COMPOSE_ONBOARDING) down -v --remove-orphans 2>/dev/null || true
