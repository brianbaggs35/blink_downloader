# Backend image: API and worker share it (different commands).
#
#   dev  — python:3.14-slim + uv, source bind-mounted, hot reload
#   prod — Chainguard (Wolfi), non-root
#
# Both targets carry ffmpeg (clip duration probing + thumbnail generation).
# ffmpeg's shared-library closure (X11/cairo/harfbuzz/sdl2, ~50 packages) is
# large enough that hand-copying just the .so files into the fully distroless
# `python:latest` base is impractical, so prod uses the `-dev` tag (has apk +
# a shell) as its runtime base instead — installed as root, then dropped to
# `nonroot` before serving. Everything else (non-root, Wolfi's near-zero-CVE
# package builds, read-only rootfs + cap_drop ALL in compose) still applies.

FROM ghcr.io/astral-sh/uv:latest AS uv-binary

# ---------------------------------------------------------------- dev target
FROM python:3.14-slim AS dev
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
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
# insightface hard-requires full opencv-python (needs libGL/libGTK), but this
# image is headless and Wolfi never carries GL — import cv2 would fail at
# runtime otherwise. uv/pip have no package-identity substitution, so both
# wheels would install to the same cv2/ path in undefined order; force the
# headless build (same upstream version, GL-free) to win explicitly instead.
RUN uv sync --frozen --no-dev --no-install-project \
    && uv pip install --python /app/.venv/bin/python --force-reinstall opencv-python-headless==5.0.0.93

# --------------------------------------------------------------- prod target
FROM cgr.dev/chainguard/python:latest-dev AS prod
USER root
RUN apk add --no-cache ffmpeg
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"
COPY --from=builder /app/.venv /app/.venv
COPY backend/alembic.ini /app/alembic.ini
COPY backend/alembic /app/alembic
COPY backend/app /app/app
RUN chown -R nonroot:nonroot /app
USER nonroot
ENTRYPOINT []
CMD ["/app/.venv/bin/python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
