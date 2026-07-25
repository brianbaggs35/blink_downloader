# Frontend image: Vite build served by Chainguard nginx with TLS termination
# and an /api reverse proxy to the backend service.

FROM cgr.dev/chainguard/node:latest-dev AS builder
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM cgr.dev/chainguard/nginx:latest AS prod
COPY docker/nginx.conf /etc/nginx/nginx.conf
COPY --from=builder /app/dist /usr/share/nginx/html
EXPOSE 8080 8443
