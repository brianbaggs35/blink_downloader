# Consolidated production image: nginx (frontend) + API + worker, supervised
# together in one container - what `docker-compose.yml`'s `app`/`migrate`
# services actually ship. Dev (hot reload) and e2e (isolated per-service
# containers, coverage instrumentation) still build backend.Dockerfile/
# frontend.Dockerfile directly - this file is prod-only.

FROM ghcr.io/astral-sh/uv:latest AS uv-binary

# ------------------------------------------------------------ frontend build
FROM cgr.dev/chainguard/node:latest-dev AS frontend-builder
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ------------------------------------------------------------- backend build
FROM cgr.dev/chainguard/python:latest-dev AS backend-builder
COPY --from=uv-binary /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
# insightface hard-requires full opencv-python (needs libGL/libGTK), but this
# image is headless and Wolfi never carries GL - import cv2 would fail at
# runtime otherwise. uv/pip have no package-identity substitution, so both
# wheels would install to the same cv2/ path in undefined order; force the
# headless build (same upstream version, GL-free) to win explicitly instead.
RUN uv sync --frozen --no-dev --no-install-project \
    && uv pip install --python /app/.venv/bin/python --force-reinstall opencv-python-headless==5.0.0.93

# --------------------------------------------------------------- prod stage
FROM cgr.dev/chainguard/python:latest-dev AS prod
USER root
# supervisord (process supervision for this image's 3 sibling processes)
# comes from Wolfi's own apk package, not pip's `supervisor` - pip's build
# imports the legacy pkg_resources API at runtime, which current setuptools
# no longer ships by default (ModuleNotFoundError, verified empirically).
RUN apk add --no-cache ffmpeg nginx tini supervisor
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"
COPY --from=backend-builder /app/.venv /app/.venv
COPY backend/alembic.ini /app/alembic.ini
COPY backend/alembic /app/alembic
COPY backend/app /app/app
COPY --from=frontend-builder /app/dist /usr/share/nginx/html
COPY docker/nginx.app.conf /etc/nginx/nginx.conf
COPY docker/supervisord.conf /etc/supervisord.conf
# A brand-new named volume mounted at a path that doesn't exist in the image
# is created root:root by the container runtime, which nonroot can never
# write to. Pre-creating the directories here means Docker's volume-seeding
# (copy the image's dir + ownership onto a fresh, empty volume on first
# mount) carries nonroot ownership over instead - verified empirically.
RUN mkdir -p /data/clips /data/insightface \
    && chown -R nonroot:nonroot /app /data /usr/share/nginx/html /etc/supervisord.conf
USER nonroot
ENTRYPOINT ["/sbin/tini", "--"]
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisord.conf"]
