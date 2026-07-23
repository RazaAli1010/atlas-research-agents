# Atlas — Autonomous Research & Report Agent

Atlas plans a research topic into sections, pauses for human approval, researches
sections in parallel, self-corrects via review, and synthesizes a cited Markdown report —
streamed live to a React frontend.

See `CLAUDE.md` for the full spec and `specs/` for per-feature specs.

## Repository layout

```
atlas-research-agents/
├── docker-compose.yml        # Postgres (dev DB)
├── .github/workflows/ci.yml  # backend + frontend CI
├── backend/                  # FastAPI + LangGraph (Python 3.12, uv)
└── frontend/                 # React 19 + TS + Vite + Tailwind v4
```

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (Python 3.12)
- Node.js 20+
- Docker + Docker Compose

---

## F1 — Scaffolding, config & dev environment

A running skeleton: FastAPI `/api/health`, a dark React app shell, Postgres in Docker,
green CI. No graph/LLM/page logic yet — later features fill in the stubbed modules.

### 1. Database

```bash
docker compose up -d postgres
docker compose ps            # postgres should report "healthy"
```

### 2. Backend

```bash
cd backend
cp ../.env.example .env       # IMPORTANT: .env must live in backend/ (pydantic-settings
                             # loads it relative to the process cwd)
uv sync
uv run ruff check . && uv run mypy app && uv run pytest
uv run uvicorn app.main:app --reload
# → http://localhost:8000/api/health returns {"status":"ok"}
```

`app/config.py` `Settings` fails fast at startup if a required key
(`OPENAI_API_KEY`, `TAVILY_API_KEY`) is missing. `CORS_ORIGINS` is a comma-separated list.

### 3. Frontend

```bash
cd frontend
npm install
npm run lint && npm run typecheck && npm run test
npm run dev
# → http://localhost:5173 shows the dark Atlas shell (sidebar: New Run / History)
```

---

## F2 — Graph state, planner node & walking skeleton graph

The typed `ResearchState` (`app/graph/state.py`, the single source of truth for §5) plus a
minimal compiled graph `START → planner → writer → END`. The planner decomposes a topic into
3–6 sections via structured output; the writer (F2 stub) renders them as a Markdown outline.
Every LLM call goes through `app/llm/router.py` (`get_model` / `track_usage`), and token cost is
recorded into `usage_log`. Interrupts, worker fan-out, tools, and the reviewer arrive in F3–F5.

### Run the skeleton

```bash
cd backend
# .env must live in backend/ (see F1) with a real OPENAI_API_KEY
uv run python -m app.graph.demo "Compare vector database pricing for a startup"
# → prints a 3–6 item plan outline and `total_cost_usd:` (4 decimals, e.g. 0.0002)
```

Set `LANGSMITH_TRACING=true` (+ a valid `LANGSMITH_API_KEY`) to see the run in the LangSmith
`atlas` project with named `planner` / `writer` nodes. The FastAPI server enables tracing
the same way (via `enable_langsmith` in `create_app`); when tracing is on, each run's
LangSmith root run id is captured (`collect_runs`) and surfaced as `RunDetail.trace_id`, which
the frontend (F11) turns into a "View trace in LangSmith" deep-link.

### Verify

```bash
cd backend
uv run pytest && uv run ruff check . && uv run mypy app
```

The checkpointer backend is selected by `CHECKPOINT_BACKEND` (`sqlite` dev → `atlas_checkpoints.sqlite`,
`postgres` prod). Tests use an in-memory / temp-file saver and mock the model, so they run offline.

### Configuration

All config is environment-driven (12-factor). Copy `.env.example` → `backend/.env` and
fill real values for local LLM/search/tracing. Never commit `.env`.

| Var | Required | Default | Notes |
| --- | --- | --- | --- |
| `OPENAI_API_KEY` | ✅ | — | sole LLM provider |
| `TAVILY_API_KEY` | ✅ | — | web search |
| `RAG_SERVICE_URL` | | — | optional RAG service base URL; unset → `rag_search` tool disabled |
| `DEFAULT_MODEL` | | `openai:gpt-4o-mini` | default chat model (provider-prefixed) |
| `LANGSMITH_API_KEY` | | — | tracing (optional) |
| `LANGSMITH_TRACING` | | `false` | |
| `LANGSMITH_PROJECT` | | `atlas` | |
| `DATABASE_URL` | | `postgresql://atlas:atlas@localhost:5432/atlas` | matches compose creds |
| `CHECKPOINT_BACKEND` | | `sqlite` | `sqlite` \| `postgres` |
| `CORS_ORIGINS` | | `http://localhost:5173` | comma-separated |

## F3 — Tools & parallel worker fan-out (Send API)

Workers now research each planned section **in parallel** using real tools, and the writer
merges their drafts into a cited report. Topology becomes
`START → planner → [fan_out] worker×N → writer → END`.

- **Tools** (`app/tools/`, each a `@tool` with an LLM-facing docstring):
  - `web_search` — Tavily (`langchain-tavily`), ≤5 results normalized to `{url,title,content}`,
    content truncated to 1,000 chars; degrades to `[]` on error/zero results.
  - `rag_search` — POSTs the user's RAG service at `RAG_SERVICE_URL`; **self-disables** (not
    registered, logs a warning) when the var is unset, so the graph runs without it.
  - `calculator` — safe arithmetic via `ast` parsing (no `eval`); rejects `__import__`,
    attribute/function access, and oversized exponents.
- **Worker** (`app/graph/nodes/worker.py`) — a hand-written, bounded ReAct loop (`.bind_tools`,
  no prebuilt agents). Caps at `MAX_TOOL_CALLS_PER_WORKER` (8) tool calls; if run cost ≥
  `RUN_COST_CEILING_USD` it skips tools and drafts from context (flagged). Sources are numbered
  as tools return so every `[n]` marker resolves to a `Source`. Has a revision code path
  (feedback + previous draft) that F4 will wire to the reviewer.
- **Routing** (`app/graph/routing.py`) — `fan_out(state)` emits one `Send("worker", …)` per section.
- **Writer** (`app/graph/nodes/writer.py`) — `merge_drafts()` merges drafts in plan order, dedupes
  sources globally, remaps `[n]` markers to global indices, and appends a `## Sources` list.

### Run it

```bash
cd backend
# .env in backend/ with real OPENAI_API_KEY + TAVILY_API_KEY
uv run python -m app.graph.demo "Compare vector database pricing for a seed-stage startup"
# → a multi-section report; each section carries [n] markers resolvable to the closing ## Sources
```

With `LANGSMITH_TRACING=true`, the LangSmith `atlas` project shows overlapping `worker` branch
timestamps (parallel proof). The graph completes even with `RAG_SERVICE_URL` unset and with Tavily
returning zero results — affected sections note the source gap.

### Verify

```bash
cd backend
uv run pytest && uv run ruff check . && uv run mypy app
```

## F4 — Reviewer node & self-correction loop

The signature LangGraph cycle. A reviewer grades each section's latest draft; weak
sections loop back to the workers with concrete feedback; the loop is hard-capped by
the revision budget. Topology becomes
`START → planner → [fan_out] worker×N → reviewer → (workers | writer) → END`.

- **Reviewer** (`app/graph/nodes/reviewer.py`) — grades each section's newest *unreviewed*
  draft via structured output (`.with_structured_output(Review, …)`) against a rubric
  (objective coverage, every claim cited, **grounding** — each cited claim follows from its
  source excerpt — and coherence). The draft's sources are rendered *with their excerpts* so
  the reviewer can judge grounding, and the rubric approves any adequate draft (reserving
  `revise` for substantive gaps, never stylistic polish) to avoid needless revision loops.
  `verdict` is normalized server-side: `score < 0.7 ⇒ "revise"`, and feedback is guaranteed
  non-empty on a revise. Logs one `UsageEvent` per graded section and recomputes
  `revision_counts[sid]` (= revisions produced so far = highest draft revision).
- **Routing** (`app/graph/routing.py::route_after_review`) — the *sole* revision-budget gate
  (the termination guarantee). Re-sends only sections whose latest verdict is `revise`, that
  have produced fewer than `MAX_REVISIONS_PER_SECTION` (2) revisions, **and** whose last
  revision raised the reviewer score by at least `_MIN_SCORE_GAIN` (0.05) — a stalled section
  stops early instead of burning the rest of its budget on non-converging passes (the common
  source of wasted revision loops). The first revision is always allowed (no prior score to
  compare). Carries `{feedback, previous_draft}`; otherwise routes to the writer. The score-gain
  gate only ever *removes* dispatches, so each section is still dispatched at most
  `1 + MAX_REVISIONS_PER_SECTION` times — the loop provably terminates.
- **Writer** (`app/graph/nodes/writer.py`) — now selects each section's highest-revision
  **approved** draft (else the best-scoring draft), and prepends a *Limitations* note when a
  section exhausts its budget without approval.

### Run it

```bash
cd backend
# .env in backend/ with real OPENAI_API_KEY + TAVILY_API_KEY
LANGSMITH_TRACING=true uv run python -m app.graph.demo \
  "Give exact 2026 per-GB monthly storage prices for Pinecone, Weaviate, and Qdrant with a break-even table"
# → deliberately hard topic; `Drafts produced` exceeds the section count when a
#   section is revised, and the revised section appears in the final report.
```

With `LANGSMITH_TRACING=true`, the LangSmith `atlas` trace shows at least one
`worker → reviewer → worker → reviewer → writer` revise→improve cycle.

### Verify

```bash
cd backend
uv run pytest && uv run ruff check . && uv run mypy app
# test_graph_review_loop.py proves an always-revise reviewer still halts within budget.
```

## F5 — Human-in-the-loop approval gate (interrupt + Command resume)

The graph pauses after planning so a human can review or edit the plan before any
expensive research runs. The pause is a LangGraph `interrupt()`, persisted by the
checkpointer, so a run can be **killed at the pause and resumed by a fresh process**.
Topology becomes
`START → planner → approval_gate(interrupt) → [fan_out] worker×N → reviewer → (workers | writer) → END`.

- **Approval gate** (`app/graph/nodes/approval.py::approval_gate`) — a single
  `interrupt({"plan": [...]})` as the node's first statement (no prior side effects, so
  re-execution on resume is safe). Resume payloads:
  - `{"action": "approve"}` — keep the plan.
  - `{"action": "edit", "plan": [ {id, title, objective, suggested_queries}, ... ]}` — replace it;
    the edited list is clamped to `MAX_SECTIONS` (6).

  Either way the node sets `plan_approved=True` and advances `status` to `researching`, so the
  fan-out dispatches one worker per (possibly edited) section.
- **Run metadata** (`app/persistence/runs_repo.py::RunsRepo`) — a thin, hand-written store for the
  `runs` table (`run_id`, `thread_id`, `topic`, `status`, `created_at`, `cost_usd`, `report_md`).
  Backend-selected exactly like the checkpointer: stdlib `sqlite3` on `atlas_runs.sqlite` in dev,
  `psycopg` over `DATABASE_URL` in prod. **Deliberate tradeoffs:** the schema is bootstrapped with a
  `CREATE TABLE IF NOT EXISTS` on construction (no Alembic — overkill for one append-mostly table),
  and in dev the `runs` metadata lives in its own sqlite file beside the checkpoints.
- **Run lifecycle** (`app/services/run_service.py::RunService`) — the orchestrator the API (F6) will
  call. `start(topic)` creates the run row and drives the graph to the approval pause; `resume(run_id,
  decision)` feeds the decision back with `Command(resume=...)`. Each call opens a *fresh* checkpointer
  and graph (no long-lived connection) — which is exactly what makes resume survive a restart — and the
  synchronous graph/saver work is offloaded via `asyncio.to_thread`. The run row tracks the lifecycle
  `planning → awaiting_approval → researching → done` with `cost_usd`.

### Run it

```bash
cd backend
# .env in backend/ with a real OPENAI_API_KEY
uv run python -m app.graph.demo \
  "Compare vector database pricing for a seed-stage startup" --interactive --thread demo-f5
# → prints the proposed plan and waits: y = approve, e = edit (keep first N sections).
#   Press Ctrl-C AT THE PAUSE to kill the process, then rerun the SAME command:
uv run python -m app.graph.demo \
  "Compare vector database pricing for a seed-stage startup" --interactive --thread demo-f5
# → re-attaches to thread demo-f5, reprints the persisted plan, and 'y' resumes to a
#   finished report + total_cost_usd — proving checkpointer durability across processes.
```

Without `--interactive` the demo auto-approves at the pause so a run completes in one shot.

### Verify

```bash
cd backend
uv run pytest && uv run ruff check . && uv run mypy app
# test_approval_restart.py proves resume survives a fresh graph over the same sqlite file;
# test_approval_interrupt.py proves editing the plan changes the fan-out;
# test_run_service.py proves the runs row transitions planning → awaiting_approval → done.
```

## F9 — Model routing & cost optimization

Each graph role is routed to a cost-appropriate OpenAI model behind the unchanged
`get_model(role)` seam (`app/llm/router.py`). The default `MODEL_ROUTING` sends
planner/reviewer/writer to the strong tier (`openai:gpt-4o`) and the high-volume fan-out
worker to the cheap tier (`openai:gpt-4o-mini`). `GET /api/runs/{id}` now returns a
`cost_breakdown: {node: cost_usd}` derived from `usage_log`.

Override routing via the `MODEL_ROUTING` env var (JSON; roles omitted fall back to
`DEFAULT_MODEL`; unknown role keys are rejected at startup):

```bash
# force everything onto the strong model
MODEL_ROUTING='{"planner":"openai:gpt-4o","reviewer":"openai:gpt-4o","writer":"openai:gpt-4o","worker":"openai:gpt-4o"}' \
  uv run python -m app.graph.demo "Compare vector database pricing for a seed-stage startup"
```

The cost comparison across all-gpt-4o / routed / all-gpt-4o-mini (n=20, seed 42) and the
chosen default live in `backend/evals/EXPERIMENTS.md`.

### Verify

```bash
cd backend
uv run pytest tests/test_router_routing.py tests/test_config_routing.py tests/test_cost_breakdown.py -q
git diff --stat -- app/graph/nodes/   # empty: routing changed no node code
# Full comparison (real OpenAI + Tavily calls, needs live keys) — see evals/EXPERIMENTS.md:
uv run python evals/run_benchmark.py --n 20 --seed 42
```

---

## F10 — Frontend foundation: API layer, design system & New Run flow

A production-feeling React shell: a typed API client + TanStack Query hooks, a reconnecting
SSE hook feeding a Zustand store, a hand-built Tailwind UI kit, `react-router` v7 routing,
and a working New Run flow that lands on `/runs/:id` in a live connection state.

### Configuration

- **`react-router@^7`** is a runtime dependency (declarative/library mode — import router
  primitives from `react-router`, **not** `react-router-dom`). Fresh clones get it via
  `npm install`; if adding to an older checkout run `npm i react-router@^7`.
- **`VITE_API_URL`** (see `frontend/.env.example`) is the API base URL. Leave it **empty**
  for local dev — same-origin requests hit the Vite dev proxy, which forwards `/api` →
  `http://localhost:8000` (no CORS). In production (F13) set it to the API origin.

### Run it

```bash
# terminal 1 — backend (dev, sqlite)
cd backend && uv run uvicorn app.main:app --port 8000

# terminal 2 — frontend
cd frontend && npm install && npm run dev
# → http://localhost:5173
#   New Run: enter "Compare vector database pricing for a seed-stage startup",
#   press ⌘/Ctrl+Enter → navigates to /runs/<id>; the Run page shows a status Badge
#   and a connection indicator ("connecting…" → "live") while SSE events accumulate.
# → http://localhost:5173/dev/kit — visual QA of every UI-kit variant (dev build only).
# → stop & restart the backend while on /runs/<id> → "reconnecting…", then the hook
#   replays the full run history without duplication (F6 replays its buffer per connect).
```

### Verify

```bash
cd frontend
npm run test && npx tsc --noEmit && npm run lint
# 18 vitest specs pass (envelope round-trip, SSE reconnect, keyboard nav, client,
# New Run create flow, query invalidation); tsc + eslint clean.
```
