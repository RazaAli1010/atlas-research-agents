# Deploying Atlas

Atlas ships as three containers — `postgres`, `backend` (FastAPI + LangGraph), and
`frontend` (nginx serving the built SPA and proxying `/api`). `docker compose up --build`
from a fresh clone plus a filled `.env` is a fully working deployment; everything below is
what you need to run it somewhere real.

---

## Environment matrix

All backend config is 12-factor (env vars, read by `pydantic-settings` in
`backend/app/config.py`). Frontend config is build-time (`VITE_*`, inlined by Vite).

| Variable | Required | Secret | Dev default | Compose value | Notes |
| --- | :---: | :---: | --- | --- | --- |
| `OPENAI_API_KEY` | ✅ | ✅ | — | from `.env` | Sole LLM provider. Fail-fast if missing. |
| `TAVILY_API_KEY` | ✅ | ✅ | — | from `.env` | Web search tool. Fail-fast if missing. |
| `CHECKPOINT_BACKEND` | | | `sqlite` | **`postgres`** (override) | Selects the checkpointer + runs store. |
| `DATABASE_URL` | | | `postgresql://atlas:atlas@localhost:5432/atlas` | **`…@postgres:5432/atlas`** (override) | Used only when backend is `postgres`. |
| `CORS_ORIGINS` | | | `http://localhost:5173` | **`http://localhost`** (override) | Comma-separated allowed origins. |
| `DEFAULT_MODEL` | | | `openai:gpt-4o-mini` | from `.env` | Per-role fallback model. |
| `MODEL_ROUTING` | | | routed (worker→mini, rest→4o) | from `.env` | JSON role→model map (F9). |
| `LANGSMITH_TRACING` | | | `false` | from `.env` | Enable tracing. |
| `LANGSMITH_API_KEY` | | ✅ | — | from `.env` | Required only when tracing is on. |
| `LANGSMITH_PROJECT` | | | `atlas` | from `.env` | Trace project name. |
| `EVAL_JUDGE_MODEL` / `EVAL_SMOKE_MODEL` | | | `openai:gpt-4o` / `-mini` | from `.env` | Eval harness only (not the graph). |
| `RAG_SERVICE_URL` | | | — (unset → tool disabled) | from `.env` | Optional external RAG service. |
| `VITE_API_URL` (frontend build) | | | empty (same-origin) | empty | Leave empty behind the nginx proxy. |
| `VITE_LANGSMITH_BASE_URL` (frontend build) | | | empty | build arg (optional) | LangSmith trace deep-link base. |

The three **compose overrides** (`CHECKPOINT_BACKEND`, `DATABASE_URL`, `CORS_ORIGINS`) are set
in `docker-compose.yml` under `backend.environment`, which takes precedence over `env_file`, so
the values in your `.env` for those only affect host-mode dev.

---

## The single-worker constraint (read this before scaling)

The backend runs **one uvicorn worker on purpose**. The SSE layer
(`backend/app/api/routes_runs.py`) keeps an **in-process, in-memory** `RunRegistry` — each
run's event history and its live subscriber queues live in that one process, and each graph
runs as a per-run `asyncio` task inside it.

**Consequence:** do not run `--workers N`, a multi-worker gunicorn, or more than one backend
replica as-is. A second worker would serve `/api/runs/{id}/events` from an empty buffer and
never see a run started by the other worker. `docker-compose.yml` therefore has no `--workers`
flag, and a horizontally scaled deployment needs the change below first.

**What a real fix looks like:**
- Move graph execution off the request process onto a **task queue** (Celery / RQ / Arq / a
  LangGraph platform worker), so any worker can start/resume any run.
- Fan SSE out through a **broker** — publish each `AtlasEvent` to Redis pub/sub (or Postgres
  `LISTEN/NOTIFY`) and have every API replica subscribe, so `/events` works regardless of which
  worker owns the run.
- Run state itself already survives this: it lives in the Postgres checkpointer + `runs` table,
  not in memory. Only the **event transport** and **task dispatch** need externalizing — the
  durable-resume behaviour (below) already proves the state layer is ready.

This is why the compose stack is a faithful single-node deployment but not a horizontally
scaled one.

---

## Durable state (the project's thesis)

The checkpointer is Postgres in compose (`CHECKPOINT_BACKEND=postgres`). Because
`RunService.start/resume` open a fresh checkpointer + graph per call and persist to Postgres,
a run interrupted at the approval gate **survives a full backend restart**:

```bash
# start a run in the browser, stop at the approval pause, then:
docker compose restart backend
# approve in the browser → the run resumes from the Postgres checkpoint to a finished report.
```

Nginx re-resolves the backend hostname on each request (Docker DNS resolver in `nginx.conf`),
so the restarted container is reached without a stale-IP 502.

---

## Postgres persistence & backup

- Checkpoints and run metadata live in the named volume `atlas_pgdata`
  (`/var/lib/postgresql/data`). It persists across `docker compose up/down`; **`docker compose
  down -v` deletes it** (and with it all run history + in-flight interrupts).
- Back up with `pg_dump`:
  ```bash
  docker compose exec postgres pg_dump -U atlas atlas > atlas-backup.sql
  # restore:
  docker compose exec -T postgres psql -U atlas atlas < atlas-backup.sql
  ```
- In managed/hosted Postgres, point `DATABASE_URL` at it and drop the `postgres` service from
  compose (or ignore it). No schema migration step is needed — the checkpointer calls
  `setup()` and `RunsRepo` uses `CREATE TABLE IF NOT EXISTS`, so a cold database self-bootstraps
  on first run.

---

## CORS

With the nginx same-origin proxy, the browser calls `/api` on the **same origin** it loaded the
SPA from, so CORS is effectively unused — `CORS_ORIGINS=http://localhost` (or your real domain,
e.g. `https://atlas.example.com`) is enough.

If you split the SPA and API onto **different** origins (static CDN for the SPA + a separate API
host), then:
1. Set `CORS_ORIGINS` on the backend to the SPA's origin, and
2. Build the frontend with `VITE_API_URL=https://api.example.com` so it calls the API host
   directly (bypassing the nginx proxy). SSE still needs `proxy_buffering off` on whatever proxy
   sits in front of the API.

---

## Deploying to a host

The stack is host-agnostic — anything that runs `docker compose` (a VPS, Railway, Render, Fly.io)
works. Generic steps:

1. Provision Postgres (the compose `postgres` service, or a managed instance → set `DATABASE_URL`).
2. Set secrets (`OPENAI_API_KEY`, `TAVILY_API_KEY`, optionally `LANGSMITH_*`) as env/secret vars,
   not committed files.
3. Build + run the two images; expose the frontend on `:80`/`:443`, keep the backend private.
4. Put TLS termination (a load balancer, Caddy, or the platform's HTTPS) in front of the frontend;
   ensure it also does **not buffer** the `/api/runs/*/events` route.

### Worked example — Fly.io

```bash
# backend (single machine — the single-worker constraint means min 1, and don't autoscale >1)
cd backend
fly launch --no-deploy                 # generates fly.toml; set internal_port = 8000
fly postgres create --name atlas-db    # managed Postgres
fly postgres attach atlas-db           # sets DATABASE_URL secret
fly secrets set OPENAI_API_KEY=sk-... TAVILY_API_KEY=tvly-... \
               CHECKPOINT_BACKEND=postgres CORS_ORIGINS=https://atlas-web.fly.dev
# in fly.toml: [http_service] set min_machines_running = 1 (no scale-to-zero mid-run),
#              and do NOT set a max > 1 machine for the backend.
fly deploy

# frontend (second app; nginx image). Point its /api proxy at the backend app's internal
# address, or build with VITE_API_URL=https://<backend-app>.fly.dev and drop the proxy.
cd ../frontend
fly launch --no-deploy                 # internal_port = 80
fly deploy
```

The same shape maps to Railway (two services + a Postgres plugin) or a VPS (`docker compose up -d`
behind Caddy/nginx for TLS).
