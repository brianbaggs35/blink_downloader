# Backend image: API and worker share it (different commands).
#
#   dev  — python:3.14-slim + uv, source bind-mounted, hot reload
#   prod — Chainguard (Wolfi) distroless Python, non-root, no shell

FROM ghcr.io/astral-sh/uv:latest AS uv-binary

# ---------------------------------------------------------------- dev target
FROM python:3.14-slim AS dev
COPY --from=uv-binary /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# -------------------------------------------------------------- build stage
FROM cgr.dev/chainguard/python:latest-dev AS builder
COPY --from=uv-binary /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# --------------------------------------------------------------- prod target
FROM cgr.dev/chainguard/python:latest AS prod
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"
COPY --from=builder /app/.venv /app/.venv
COPY backend/alembic.ini /app/alembic.ini
COPY backend/alembic /app/alembic
COPY backend/app /app/app
USER nonroot
ENTRYPOINT []
CMD ["/app/.venv/bin/python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
