## F13 — Deployment, CI hardening & README

**Goal:** A fresh clone plus a filled `.env` runs the whole app with one `docker compose up`, survives a backend restart mid-approval (Postgres durable-state proof), and ships a README a hiring manager can evaluate in 5 minutes.

**Depends on:** F1 (compose/Postgres, config, CI), F2 (`create_app`, checkpointer factory), F5 (`RunService` resume, `RunsRepo`), F6 (SSE endpoint `GET /api/runs/{id}/events`, single-worker in-memory registry), F7 (`GET /api/runs/{id}/report.md`), F8 (benchmark reports in `backend/evals/`), F9 (`MODEL_ROUTING`, cost experiment), F10–F12 (React SPA consuming §7, `VITE_API_URL` same-origin design).

### Context digest

Grounded against the actual repo (verified this session), not memory.

**Backend runtime (verified):**
- `backend/pyproject.toml`: `requires-python = ">=3.12"`, uv-managed, `[tool.uv] package = false` (uv installs deps into a venv; app is run as a module, not installed). Runtime deps already include `langgraph-checkpoint-postgres`, `uvicorn[standard]`, `httpx`, `psycopg` (transitively via checkpoint-postgres).
- Entry point: `app.main:app` (`backend/app/main.py::create_app`). Health route `GET /api/health → {"status":"ok"}` is defined there. CORS middleware reads `settings.CORS_ORIGINS`.
- `backend/app/config.py::Settings` (pydantic-settings): `env_file=".env"` is optional — when absent (as in a container), real env vars are used. Required: `OPENAI_API_KEY`, `TAVILY_API_KEY` (fail-fast at construction). Selected-by-config: `CHECKPOINT_BACKEND` (`sqlite`|`postgres`, default `sqlite`), `DATABASE_URL` (default `postgresql://atlas:atlas@localhost:5432/atlas`), `CORS_ORIGINS` (comma-separated string → `list[str]`, default `http://localhost:5173`).
- `backend/app/persistence/checkpointer.py::checkpointer_cx` already calls `cp.setup()` on both `SqliteSaver` and `PostgresSaver` every time it opens — so a **cold Postgres gets its checkpoint tables created automatically** on first run/resume. `RunsRepo` likewise bootstraps its `runs` table with `CREATE TABLE IF NOT EXISTS`. No migration step is needed for cold start.
- **Single-worker constraint (F6, load-bearing):** `backend/app/api/routes_runs.py` keeps an in-process, in-memory `RunRegistry`/`RunStream` (SSE history + subscriber queues) and runs each graph as a per-run asyncio background task. This is only correct with **one** uvicorn worker. The Dockerfile/compose MUST run a single worker (no `--workers N`, no gunicorn multi-worker). The event buffer is ephemeral (lost on restart); durable run state lives in Postgres.

**API surface (§7 — all routes already implemented, verified in `routes_runs.py`):**
```
POST   /api/runs                      (l.196)  201 {run_id, thread_id}
GET    /api/runs                      (l.213)  200 [RunSummary]
GET    /api/runs/{run_id}             (l.229)  200 RunDetail (+cost_breakdown, +trace_id, +sources)
GET    /api/runs/{run_id}/report.md   (l.240)  200 markdown
POST   /api/runs/{run_id}/resume      (l.269)  202
GET    /api/runs/{run_id}/events      (l.305)  SSE stream          ← nginx must NOT buffer this
GET    /api/health                    (main.py) 200 {status:"ok"}
```

**Frontend build (verified):**
- `frontend/package.json`: `"build": "tsc -b && vite build"` → static bundle in `dist/`. Node 20 (matches CI `frontend` job). Install with `npm ci` (lockfile committed).
- `frontend/src/api/client.ts`: `const API_BASE = (import.meta.env.VITE_API_URL ?? '').replace(/\/$/,'')` — **empty `VITE_API_URL` ⇒ same-origin `/api`.** The SSE hook (`useRunEvents.ts`) builds `EventSource` URLs the same way. So in production the browser calls same-origin `/api/...` and **nginx proxies `/api` to the backend** — no CORS preflight, no build-time API URL needed. `VITE_LANGSMITH_BASE_URL` (optional) is the only build-time value worth wiring as a build arg.
- `frontend/vite.config.ts` dev proxy (`/api → http://localhost:8000`) is dev-only; nginx replaces it in prod.

**CI (verified, `.github/workflows/ci.yml`):** two jobs today — `backend` (uv sync → ruff → mypy `app evals` → pytest, with dummy `OPENAI_API_KEY`/`TAVILY_API_KEY` env) and `frontend` (npm ci → eslint → tsc → vitest). A separate `evals-smoke.yml` exists and stays **manual** (per F8). F13 adds Docker-build + `docker compose config` jobs.

**Real benchmark numbers for the README (verified, do not invent):**
- `backend/evals/SAMPLE_RESULTS.md` (n=4, seed 42, cheap-tier smoke, strong judge): success rate **25.0%**, latency **p50 60.8s / p95 121.2s**, mean cost **$0.0883/run**. Failure taxonomy: **groundedness = 75% of failures** (3/4 runs). Per-run scores present (structure/citation/coverage all 1.0; groundedness the differentiator). Groundedness optimization moved DNS 0.4 → 0.8 (pass), cut total revision loops 39 → 15 (−62%), p50 146.3s → 60.8s (−58%).
- `backend/evals/EXPERIMENTS.md` (F9 cost, derived): mean cost/run — all-gpt-4o **$0.3995**, routed default **$0.1250**, all-gpt-4o-mini **$0.0240 (measured)**; **routed saves 68.7% vs all-gpt-4o**. Quality-within-3-points gate explicitly **not yet verified** (needs live n=20 run) — report this honestly, do not claim it passed.
- **n=4 caveat is mandatory** in the README table — these are a smoke sample, not a full benchmark.

**Graph topology for the Mermaid diagram (§6, exact):**
`START → planner → approval_gate(interrupt) → [Send fan-out] worker×N → reviewer → (revise↺ per section ≤2 | writer) → END`.

**Design system (§8) for README/DEPLOYMENT visuals:** dark-first; costs monospace 4 decimals. Keep any diagrams consistent with that calm/technical tone.

### Context deltas

These are additive infra/docs — **no change to `ResearchState` (§5) or the API contract (§7).** They should be reflected in the shared context's repo layout (§4) and are called out here so they are approved before implementation:

1. **New files** not yet in §4: `frontend/nginx.conf`, `DEPLOYMENT.md` (repo root), `backend/.dockerignore`, `frontend/.dockerignore`, `docs/atlas-demo.gif` (the F11 demo capture referenced by the README hero). Add `frontend/nginx.conf` and `DEPLOYMENT.md` to §4's tree.
2. **`docker-compose.yml` scope change:** §4/F1 comment says compose is "Postgres only … Backend/frontend containers arrive in F13." F13 finalizes it to a 3-service stack. Update the F1 comment.
3. **Root `.env` doubles as the compose env file.** Today `.env.example` documents "copy to `backend/.env`" for dev. F13 also consumes a root `.env` via `docker compose` (`env_file`). One `.env.example` serves both; add a short "Docker vs dev" note to it. **New/clarified compose value:** `CORS_ORIGINS=http://localhost` for the compose stack (browser origin is `http://localhost`; same-origin via nginx means CORS is effectively unused, but set it correctly anyway).
4. **`.env.example` completeness:** ensure every var read by `Settings` and every `VITE_*` is present. `VITE_*` values live in `frontend/.env.example` (already has `VITE_API_URL`, `VITE_LANGSMITH_BASE_URL`); the root `.env.example` covers backend + compose.

If any delta is unwanted, stop and reconcile the shared context first.

### Scope

1. **`backend/Dockerfile`** — multi-stage, non-root, healthcheck.
   - **Stage `builder`:** base `ghcr.io/astral-sh/uv:python3.12-bookworm-slim` (uv preinstalled). `WORKDIR /app`. Copy `pyproject.toml uv.lock` first, `RUN uv sync --frozen --no-dev` (deps layer cached), then copy `app/` and `evals/`. Produces `/app/.venv`.
   - **Stage `runtime`:** base `python:3.12-slim-bookworm`. Copy `/app/.venv` and source from builder. Create a non-root user (`useradd -m -u 1000 atlas`), `USER atlas`. `ENV PATH="/app/.venv/bin:$PATH"`, `PYTHONUNBUFFERED=1`. `EXPOSE 8000`.
   - **Healthcheck (no curl in slim image — use stdlib):**
     ```dockerfile
     HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
       CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/health').status==200 else 1)"
     ```
   - **CMD (single worker — F6):** `CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]` (default 1 worker; **never** add `--workers`).
   - `backend/.dockerignore`: `.venv/`, `__pycache__/`, `*.sqlite`, `.pytest_cache/`, `tests/`, `evals/results/`, `.env`.

2. **`frontend/nginx.conf`** — static SPA + `/api` proxy, SSE-safe.
   ```nginx
   server {
     listen 80;
     server_name _;
     root /usr/share/nginx/html;
     index index.html;

     # SPA client-side routing fallback (react-router)
     location / { try_files $uri $uri/ /index.html; }

     # API + SSE → backend. proxy_buffering off is REQUIRED for the events
     # stream (GET /api/runs/{id}/events) or tokens/interrupt never flush.
     location /api/ {
       proxy_pass http://backend:8000;
       proxy_http_version 1.1;
       proxy_set_header Host $host;
       proxy_set_header X-Real-IP $remote_addr;
       proxy_set_header Connection "";
       proxy_buffering off;              # SSE-safe (applies to all /api; harmless for JSON)
       proxy_cache off;
       proxy_read_timeout 3600s;         # long-lived SSE connections
       chunked_transfer_encoding off;
     }
   }
   ```
   (One `/api/` location with `proxy_buffering off` satisfies the events-route requirement and is simpler than a regex split; the comment states why.)

3. **`frontend/Dockerfile`** — node builder → nginx runtime.
   - **Stage `builder`:** `node:20-bookworm-slim`. `WORKDIR /app`. Copy `package.json package-lock.json`, `RUN npm ci`, copy rest, optionally `ARG VITE_LANGSMITH_BASE_URL` + `ENV VITE_LANGSMITH_BASE_URL=$VITE_LANGSMITH_BASE_URL`. `RUN npm run build` → `/app/dist`. **Do not set `VITE_API_URL`** (empty = same-origin, which nginx proxies).
   - **Stage `runtime`:** `nginx:1.27-alpine`. `COPY --from=builder /app/dist /usr/share/nginx/html`. `COPY nginx.conf /etc/nginx/conf.d/default.conf`. `EXPOSE 80`. Optional healthcheck: `wget -qO- http://localhost/ || exit 1`.
   - `frontend/.dockerignore`: `node_modules/`, `dist/`, `.env`.

4. **`docker-compose.yml`** (finalize; replace the F1 Postgres-only file) — three services, health-gated ordering.
   ```yaml
   services:
     postgres:
       image: postgres:16
       environment:
         POSTGRES_USER: atlas
         POSTGRES_PASSWORD: atlas
         POSTGRES_DB: atlas
       volumes: [ "atlas_pgdata:/var/lib/postgresql/data" ]
       healthcheck:
         test: ["CMD-SHELL", "pg_isready -U atlas -d atlas"]
         interval: 5s
         timeout: 5s
         retries: 5
       # ports optional in prod; keep 5432 exposed only for local debugging

     backend:
       build: { context: ./backend }
       env_file: [ .env ]                       # OPENAI/TAVILY/LANGSMITH/MODEL_ROUTING/etc.
       environment:                              # explicit overrides win over env_file
         CHECKPOINT_BACKEND: postgres
         DATABASE_URL: postgresql://atlas:atlas@postgres:5432/atlas
         CORS_ORIGINS: http://localhost
       depends_on:
         postgres: { condition: service_healthy }
       # no ports needed — only nginx reaches it on the compose network
       # exposes 8000 to the network via EXPOSE in the image

     frontend:
       build: { context: ./frontend }
       ports: [ "80:80" ]
       depends_on: [ backend ]

   volumes:
     atlas_pgdata:
   ```
   - `docker compose up --build` from a fresh clone + `.env` = working app at `http://localhost`.
   - Backend has no host port publish (reached only by nginx over the compose network); publish `8000` only if direct API debugging is wanted.

5. **Root `.env.example` — complete & compose-aware.** Keep all existing vars; add a header note that the same file seeds **both** dev (`cp .env.example backend/.env`) and Docker (`cp .env.example .env` at repo root, consumed by compose `env_file`). Ensure present: `OPENAI_API_KEY`, `TAVILY_API_KEY`, `DEFAULT_MODEL`, `MODEL_ROUTING` (commented), `EVAL_JUDGE_MODEL`, `EVAL_SMOKE_MODEL`, `RAG_SERVICE_URL` (commented), `LANGSMITH_API_KEY`, `LANGSMITH_TRACING`, `LANGSMITH_PROJECT`, `DATABASE_URL`, `CHECKPOINT_BACKEND`, `CORS_ORIGINS`. Note that compose **overrides** `CHECKPOINT_BACKEND`, `DATABASE_URL`, `CORS_ORIGINS` (so the values in `.env` only matter for host-run dev).

6. **`DEPLOYMENT.md`** (repo root) — production notes:
   - **Env matrix** table: var, required?, dev value, compose value, prod notes (mirror the §Context digest defaults; mark secrets).
   - **Single-worker constraint (from F6):** why (in-memory `RunRegistry`/SSE buffer, per-run asyncio task); consequence (do not scale the backend to >1 worker/replica as-is); **what a real fix looks like** — move graph execution to a task queue (e.g. Celery/RQ/Arq) and fan SSE out through a broker (Redis pub/sub) so any worker can serve any run's events; run state is already durable in Postgres so only the event transport and task dispatch need externalizing.
   - **Host-agnostic deploy** + a **worked Fly.io example** (`fly launch` for backend, managed Postgres or `fly pg`, `fly deploy`; set secrets via `fly secrets set`; run the frontend as a second app or serve static via a CDN; note the single-machine/`min_machines_running=1` requirement given the single-worker constraint). Keep the generic steps applicable to Railway / a VPS with `docker compose`.
   - **Postgres persistence & backup:** the `atlas_pgdata` named volume persists checkpoints + `runs`; back it up with `pg_dump`; losing it loses run history and in-flight interrupts.
   - **CORS:** with the nginx same-origin proxy, `CORS_ORIGINS=http://localhost` (or your real domain) is sufficient; if the SPA is served from a **different** origin than the API (e.g. static CDN + separate API host), set `CORS_ORIGINS` to that SPA origin and set frontend `VITE_API_URL` to the API origin at build time.

7. **CI hardening (`.github/workflows/ci.yml`)** — add jobs (keep existing `backend`/`frontend` lint/type/test jobs unchanged; `evals-smoke.yml` stays manual):
   - `docker-build-backend`: `docker/setup-buildx-action` + `docker/build-push-action` with `context: ./backend`, `push: false`, `load: false` (build-only), layer cache via `cache-from/to: type=gha`.
   - `docker-build-frontend`: same with `context: ./frontend`.
   - `compose-config`: `runs-on: ubuntu-latest`; create a throwaway `.env` (dummy keys) then `docker compose config` to validate the merged config parses. (Interpolation of `env_file` vars needs the file to exist.)
   - These run on `pull_request` (per acceptance: "docker builds must succeed on PR").

8. **`README.md`** (the deliverable) — replace the current per-feature-log README with a product README (move the per-feature run/verify notes to keep them, e.g. a `## Feature log` section or link to `specs/`, so no verify instructions are lost):
   - **Hero:** one-line pitch + embedded demo GIF `docs/atlas-demo.gif` (see Implementation notes for capture).
   - **Architecture (Mermaid)** — the exact §6 topology:
     ````markdown
     ```mermaid
     flowchart LR
       START((start)) --> planner
       planner --> approval[approval_gate<br/>interrupt/HITL]
       approval -->|Send fan-out| worker[worker × N]
       worker --> reviewer
       reviewer -->|revise ≤2 per section| worker
       reviewer -->|all approved| writer
       writer --> END((end))
     ```
     ````
   - **Why LangGraph** paragraph: durable `interrupt()` (HITL survives process restart via the checkpointer), `Send` API for parallel worker fan-out, and **cycles** (reviewer→worker revise loop) that a DAG framework can't express — plus checkpointer-backed resume as the project's thesis.
   - **Benchmark results table** with the real numbers from §Context digest (success 25%, p50 60.8s/p95 121.2s, mean cost $0.0883/run; the F9 routing cost table $0.3995 / $0.1250 / $0.0240 and 68.7% saving). **Include the n=4 smoke caveat** and that the F9 quality-parity gate is unverified. Cite `backend/evals/SAMPLE_RESULTS.md` and `backend/evals/EXPERIMENTS.md`.
   - **Failure-taxonomy highlights:** groundedness was 75% of failures → what changed (reviewer grounding rubric with source excerpts, no-progress early-stop cutting revision loops 39→15 and p50 −58%; F4/F7).
   - **Quickstart:** (a) compose — `git clone`, `cp .env.example .env`, add keys, `docker compose up --build`, open `http://localhost`; (b) dev — the existing backend/frontend two-terminal flow.
   - **Repo map:** condensed §4 tree.
   - **Honest limitations:** single-worker/in-memory SSE registry (see DEPLOYMENT.md), n=4 benchmark, F9 quality gate open, no auth, RAG tool optional/external.

9. **Final consistency pass** (do, then record results in the PR/README):
   - Confirm every §7 route is implemented (grep `routes_runs.py` — all 7 present) **and** consumed by the frontend (`frontend/src/api/client.ts` + `useRunEvents.ts`).
   - Confirm `frontend/src/types.ts` still mirrors backend `RunDetail` (`cost_breakdown`, `trace_id`, `sources`) and `AtlasEvent`.
   - Re-run each prior feature's **Verify** block (backend `uv run pytest && ruff && mypy`; frontend `npm run test && tsc --noEmit && lint`) and note them green.

### Out of scope

- Externalizing the SSE registry / task queue (documented as the production fix in DEPLOYMENT.md; no owning feature — future work).
- Authentication / multi-tenant isolation (no feature owns it).
- Running the live F9 quality benchmark (n=20) or a new eval run — README uses the **existing** measured numbers; new eval spend is F8/F9 territory and stays manual.
- HTTPS/TLS termination and a production reverse proxy in front of nginx (host-specific; mentioned generically in DEPLOYMENT.md).
- Pushing images to a registry (CI builds are build-only, `push: false`).

### Implementation notes

- **Verified versions:** Python 3.12 (uv, `package = false`), `langgraph>=1.0,<2.0`, `langgraph-checkpoint-postgres` present (pulls `psycopg`), Node 20, Vite 8, React 19, nginx pinned to a concrete tag (`nginx:1.27-alpine`) for reproducibility. Postgres 16.
- **Cold-start Postgres works without migrations:** `checkpointer_cx` calls `cp.setup()` and `RunsRepo` uses `CREATE TABLE IF NOT EXISTS`, so the first run/resume against an empty DB creates all tables. Verify `PostgresSaver.from_conn_string(DATABASE_URL)` accepts the compose URL (no `sslmode` needed on the internal network); if psycopg complains, append `?sslmode=disable`.
- **Single worker is non-negotiable:** the in-memory `RunRegistry` means a second worker/replica would serve SSE from an empty buffer and never see another worker's run. Do not add `--workers`, gunicorn, or `deploy.replicas > 1`. This is the whole reason DEPLOYMENT.md documents the task-queue fix.
- **`env_file` + `environment` precedence:** compose applies `environment:` over `env_file:`, so `CHECKPOINT_BACKEND=postgres` / `DATABASE_URL=…@postgres` reliably override whatever the shared `.env` carries for host dev.
- **Same-origin frontend:** leave `VITE_API_URL` empty in the frontend build so the bundle calls same-origin `/api`, which nginx proxies to `backend:8000`. Setting it would break the proxy model and reintroduce CORS.
- **Restart-durability (acceptance #2) expected behavior:** the run is *interrupted* (awaiting_approval) — no background task is running, so killing/restarting the backend only drops the ephemeral SSE buffer. On resume, `RunService.resume` opens a fresh checkpointer + graph and re-drives from the Postgres checkpoint; the frontend's reconnecting SSE hook rejoins and replays. State integrity comes from Postgres, not the process.
- **Docker healthcheck without curl:** slim images lack curl; use the stdlib `urllib` one-liner (scope item 1). Compose `depends_on: condition: service_healthy` for Postgres gates backend start; the backend's own HEALTHCHECK lets `docker compose ps` show readiness.
- **GIF capture is manual:** record a run end-to-end (New Run → plan approval edit → live section timeline → streamed report) and save as `docs/atlas-demo.gif` (keep it lightweight, e.g. ≤10 MB, ~10–20s). If capture can't happen in this session, commit a placeholder and flag it — acceptance requires the real GIF before the feature is truly done.
- **Don't lose the current README's verify commands:** they're the per-feature run instructions (DoD §9 requires them). Fold them into a `Feature log` section or link `specs/` rather than deleting.

### Test plan

Infra/docs feature — "tests" are runnable build/deploy checks plus the unchanged prior suites:

- `docker build backend/` succeeds and produces an image running as a non-root user (`docker run --rm <img> id -u` ⇒ `1000`, not `0`).
- `docker build frontend/` succeeds; `docker run` serves `index.html` on `:80` and the built `dist/` contains hashed assets.
- `docker compose config` exits 0 with a dummy `.env` present (mirrors the new CI `compose-config` job).
- Cold-start E2E: `docker compose up --build` → `curl http://localhost/api/health` ⇒ `{"status":"ok"}`; a full run completes in the browser; SSE events stream through nginx (network tab shows an open `event-stream`, tokens arrive incrementally — proves `proxy_buffering off`).
- Durable-resume: start a run to the approval pause; `docker compose restart backend`; approve in the browser; the run completes (Postgres-backed).
- Existing suites stay green (consistency pass): backend `uv run pytest && uv run ruff check . && uv run mypy app evals`; frontend `npm run test && npm run typecheck && npm run lint`.

### Verify

On a fresh clone (or clean VM):
```bash
git clone <repo> && cd atlas-research-agents
cp .env.example .env            # then edit: real OPENAI_API_KEY + TAVILY_API_KEY
docker compose up --build       # postgres healthy → backend healthy → frontend on :80

# in another shell:
curl -s http://localhost/api/health          # → {"status":"ok"}
docker compose config >/dev/null && echo OK  # compose file valid

# browser: http://localhost
#   New Run → plan appears → edit + Approve with edits → section timeline advances
#   live → writer tokens stream → report renders with clickable [n] citations.

# durable-state proof (the thesis):
#   start a run, stop at the approval pause, then:
docker compose restart backend
#   back in the browser, approve → run resumes from the Postgres checkpoint to a finished report.
```
CI (on the PR): `backend`, `frontend`, `docker-build-backend`, `docker-build-frontend`, `compose-config` all green.

### Acceptance criteria

- [ ] Cold-start `docker compose up --build` from a fresh clone + `.env` yields a working app at `http://localhost`, including SSE streaming through nginx (incremental token flush, not buffered) and HITL approve/resume.
- [ ] `docker compose restart backend` mid-approval, then approving in the browser, resumes the run to completion from the Postgres checkpoint (durable-state proof).
- [ ] Backend image runs as a non-root user and its HEALTHCHECK reports healthy hitting `/api/health`; backend runs a single uvicorn worker.
- [ ] `README.md` contains the real benchmark numbers (25% success, p50 60.8s/p95 121.2s, $0.0883/run, plus the F9 routing cost table + 68.7% saving) with the n=4 caveat, the embedded `docs/atlas-demo.gif`, and the §6 Mermaid diagram.
- [ ] `DEPLOYMENT.md` exists with the env matrix, the single-worker constraint + task-queue/pub-sub fix, a worked Fly.io example, Postgres backup note, and CORS guidance.
- [ ] CI is green with lint + typecheck + tests **and** backend/frontend Docker builds + `docker compose config` validation; `evals-smoke.yml` remains manual.
- [ ] Consistency pass recorded: all 7 §7 routes implemented and consumed, `frontend/src/types.ts` mirrors `RunDetail` + `AtlasEvent`, `.env.example` complete, and every prior feature's Verify block re-runs clean.
