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
`atlas` project with named `planner` / `writer` nodes.

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
| `DEFAULT_MODEL` | | `openai:gpt-4o-mini` | default chat model (provider-prefixed) |
| `LANGSMITH_API_KEY` | | — | tracing (optional) |
| `LANGSMITH_TRACING` | | `false` | |
| `LANGSMITH_PROJECT` | | `atlas` | |
| `DATABASE_URL` | | `postgresql://atlas:atlas@localhost:5432/atlas` | matches compose creds |
| `CHECKPOINT_BACKEND` | | `sqlite` | `sqlite` \| `postgres` |
| `CORS_ORIGINS` | | `http://localhost:5173` | comma-separated |
