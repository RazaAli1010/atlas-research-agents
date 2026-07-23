# syntax=docker/dockerfile:1

# --- builder: install deps + produce the static Vite bundle -------------------
FROM node:20-bookworm-slim AS builder

WORKDIR /app

# Deps layer — cached until package.json / lockfile change.
COPY package.json package-lock.json ./
RUN npm ci

# Optional build-time LangSmith deep-link base (VITE_* are inlined at build time).
# VITE_API_URL is intentionally left EMPTY so the bundle calls same-origin /api,
# which nginx proxies to the backend — setting it would break the proxy model.
ARG VITE_LANGSMITH_BASE_URL=""
ENV VITE_LANGSMITH_BASE_URL=$VITE_LANGSMITH_BASE_URL

COPY . .
RUN npm run build

# --- runtime: nginx serving the static bundle + /api proxy --------------------
FROM nginx:1.27-alpine AS runtime

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=5 \
    CMD curl -fsS http://127.0.0.1/ >/dev/null || exit 1
