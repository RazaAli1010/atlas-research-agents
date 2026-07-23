# syntax=docker/dockerfile:1

# --- builder: resolve + install deps into /app/.venv via uv -------------------
# The uv image is built on the official python:3.12-slim-bookworm, so its system
# Python lives at /usr/local/bin/python3.12 — identical to the runtime stage.
# UV_PYTHON_DOWNLOADS=0 forces uv to use that system Python (no managed download),
# which keeps the venv's interpreter path valid after the copy into runtime.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_PYTHON_DOWNLOADS=0 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Deps layer — cached until pyproject.toml / uv.lock change. --no-dev drops
# ruff/mypy/pytest; --no-install-project is a no-op here (package = false) but
# makes the dependency-only intent explicit.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# App source (run as a module from cwd; not pip-installed — package = false).
COPY app ./app

# --- runtime: slim, non-root, healthchecked -----------------------------------
FROM python:3.12-slim-bookworm AS runtime

# libpq5: the Postgres client shared library psycopg loads at runtime (PostgresSaver
# + RunsRepo on the postgres path). The slim base omits it, so install it explicitly.
# Then a non-root user (uid 1000) — never run the API as root.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 atlas \
    && mkdir -p /app && chown atlas:atlas /app

WORKDIR /app

# Copy the resolved venv and the app source from the builder.
COPY --from=builder --chown=atlas:atlas /app/.venv /app/.venv
COPY --from=builder --chown=atlas:atlas /app/app /app/app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER atlas

EXPOSE 8000

# slim has no curl — probe /api/health with the stdlib.
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/health').status==200 else 1)"]

# Single worker is REQUIRED: the SSE RunRegistry (F6) is in-process, so a second
# worker would serve events from an empty buffer. Never add --workers.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
