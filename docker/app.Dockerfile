# Consolidated production image: nginx (frontend) + API + worker, supervised
# together in one container - what `docker-compose.yml`'s `app`/`migrate`
# services actually ship. Dev (hot reload) and e2e (isolated per-service
# containers, coverage instrumentation) still build backend.Dockerfile/
# frontend.Dockerfile directly - this file is prod-only.

FROM ghcr.io/astral-sh/uv:latest AS uv-binary

# ------------------------------------------------------------ frontend build
# --platform=$BUILDPLATFORM: this stage's output (bundled JS/CSS/HTML) is
# identical regardless of the image's target platform, so it should always
# build at the runner's native speed - without this, a cross-platform build
# (e.g. amd64 runner -> arm64 target) runs the entire npm install/build
# under QEMU emulation for no reason, which is dramatically slower than
# native for npm's file-I/O-heavy workload specifically (confirmed: over 45
# minutes stuck in `npm ci` alone under emulation, vs well under a minute
# natively).
FROM --platform=$BUILDPLATFORM cgr.dev/chainguard/node:latest-dev AS frontend-builder

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY frontend/ ./
# The license key is read from the secret's mount path, not with the mount's
# `env=` option: `env=` is a BuildKit extension that buildah (podman build)
# rejects outright ("secret should have syntax id=id[,target=path,...]"),
# while both engines mount a secret at /run/secrets/<id>. uid/gid/mode because
# that mount defaults to root:root 0400 and this stage runs as Chainguard's
# nonroot (65532). A build with no secret still works - the key is simply
# empty - but a secret that is mounted and unreadable fails the build instead
# of quietly shipping a bundle without its key (which is what a bare
# `cat ... || true` did).
# A fingerprint of the key, NOT the key: neither BuildKit nor buildah puts a
# secret's contents in the layer cache key (by design), so a changed key alone
# keeps serving the bundle cached with the old one. Pass
#   --build-arg PRIMEVUE_LICENSE_FINGERPRINT="$(sha256sum < key | cut -d' ' -f1)"
# and this step re-runs whenever the key changes; unset, nothing changes.
ARG PRIMEVUE_LICENSE_FINGERPRINT=""
RUN --mount=type=secret,id=primevue_license_key,uid=65532,gid=65532,mode=0400 \
    set -e; \
    key=/run/secrets/primevue_license_key; \
    license=""; \
    if [ -e "$key" ]; then \
        license="$(cat "$key")" || { echo "$key is mounted but unreadable" >&2; exit 1; }; \
    fi; \
    VITE_PRIMEVUE_LICENSE_KEY="$license" npm run build

# ------------------------------------------------------------- backend build
FROM cgr.dev/chainguard/python:latest-dev AS backend-builder

# BuildKit creates WORKDIR owned by the current USER (Chainguard's nonroot);
# buildah (podman build) creates it root-owned, so there `uv sync` failed with
# "failed to create directory /app/.venv: Permission denied". Pre-create it
# owned by nonroot, so both engines give this stage the same /app - and the
# stage itself still runs unprivileged.
USER 0
RUN mkdir -p /app && chown 65532:65532 /app
USER 65532:65532

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

USER 0

# supervisord (process supervision for this image's 3 sibling processes)
# comes from Wolfi's own apk package, not pip's `supervisor` - pip's build
# imports the legacy pkg_resources API at runtime, which current setuptools
# no longer ships by default (ModuleNotFoundError, verified empirically).
#
# The -dev base image ships a full C toolchain (gcc, binutils, make,
# headers) and git/pip/uv/setuptools baked in - none of it is needed once
# the venv above is already built; every supervisord.conf command execs
# its binary directly (no shell wrapping), so nothing here ever compiles
# or pip-installs anything at runtime. Strip it back out rather than ship
# a live build toolchain to anyone who can get a shell in this container.
# Wolfi's own package builds keep a near-zero baseline CVE count, so
# what's left (bash/apk-tools included, for operators who need to exec in
# and debug) is deliberately kept - this trims the live attack surface,
# it doesn't chase a fully distroless rebuild.
RUN apk add --no-cache ffmpeg nginx tini supervisor \
    && apk del --no-cache \
        build-base gcc binutils make git linux-headers pkgconf \
        glibc-dev openssl-dev jitterentropy-library-dev libxcrypt-dev \
        python-3.14-dev python-3.14-base-dev \
        py3.14-pip py3.14-pip-base py3-pip-wheel py3.14-setuptools uv wget

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
    && chown -R 65532:65532 /app /data /usr/share/nginx/html /etc/supervisord.conf

USER 65532:65532

ENTRYPOINT ["/sbin/tini", "--"]
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisord.conf"]
