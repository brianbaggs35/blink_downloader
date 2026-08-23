# Frontend image: Vite build served by Chainguard nginx with TLS termination
# and an /api reverse proxy to the backend service.

FROM cgr.dev/chainguard/node:latest-dev AS builder

# Instruments the bundle with istanbul for `make e2e-coverage` - never set
# outside that one target, so the real prod image (this Dockerfile's only
# other consumer) always gets the plain, uninstrumented build.
ARG VITE_COVERAGE=false

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY frontend/ ./
RUN --mount=type=secret,id=primevue_license_key,env=VITE_PRIMEVUE_LICENSE_KEY \
    VITE_COVERAGE=${VITE_COVERAGE} npm run build

FROM cgr.dev/chainguard/nginx:latest AS prod

COPY docker/nginx.conf /etc/nginx/nginx.conf
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 8080 8443
