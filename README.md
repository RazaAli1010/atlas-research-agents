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

### Configuration

All config is environment-driven (12-factor). Copy `.env.example` → `backend/.env` and
fill real values for local LLM/search/tracing. Never commit `.env`.

| Var | Required | Default | Notes |
| --- | --- | --- | --- |
| `OPENAI_API_KEY` | ✅ | — | sole LLM provider |
| `TAVILY_API_KEY` | ✅ | — | web search |
| `LANGSMITH_API_KEY` | | — | tracing (optional) |
| `LANGSMITH_TRACING` | | `false` | |
| `LANGSMITH_PROJECT` | | `atlas` | |
| `DATABASE_URL` | | `postgresql://atlas:atlas@localhost:5432/atlas` | matches compose creds |
| `CHECKPOINT_BACKEND` | | `sqlite` | `sqlite` \| `postgres` |
| `CORS_ORIGINS` | | `http://localhost:5173` | comma-separated |
