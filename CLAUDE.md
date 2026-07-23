# Atlas — Autonomous Research & Report Agent

> **Spec-driven development guide for Claude Code.**
> Work on ONE feature per Claude Code session. At the start of every session, paste (or reference) the **SHARED CONTEXT** section plus the single feature spec you are implementing. Never implement two features in one session. Every feature spec ends with acceptance criteria — a feature is done only when all criteria pass.

---

# SHARED CONTEXT (include in every session)

## 1. What we are building

**Atlas** is a production-grade autonomous research agent. A user submits a research topic (e.g., _"Compare vector database pricing for a seed-stage startup"_). The system:

1. **Plans** — a supervisor LLM decomposes the topic into 3–6 research sections.
2. **Pauses for human approval** — the user reviews/edits the plan before any expensive work runs (LangGraph `interrupt()`).
3. **Researches in parallel** — worker nodes fan out (LangGraph `Send` API), each researching one section using tools (web search, RAG retriever, calculator).
4. **Reviews & self-corrects** — a reviewer node grades each draft section; weak sections are routed back to workers via conditional edges (max 2 revision cycles per section).
5. **Synthesizes** — a writer node merges approved sections into a final cited Markdown report.
6. **Streams everything live** — the React frontend shows node-by-node progress over SSE, renders the approval UI when interrupted, and displays the final report.
7. **Is measurable** — an evaluation harness runs the agent against a benchmark topic set and reports task success rate, trajectory stats, cost, and latency.

## 2. Non-negotiable engineering principles

These apply to EVERY feature. If a feature spec ever appears to conflict with these, these win.

1. **LangGraph 1.x APIs only.** `langgraph.prebuilt` is deprecated (moved to `langchain.agents`) — never import from it. Use `StateGraph`, `Send`, `interrupt`, `Command`, and checkpointers from their current 1.x locations. LangGraph 1.x guarantees no breaking changes until 2.0, so pin `langgraph>=1.0,<2.0`.
2. **A checkpointer is mandatory** — `interrupt()`/resume cannot work without one. `SqliteSaver` in local dev, `PostgresSaver` (via `langgraph-checkpoint-postgres`) in Docker/production. The checkpointer backend is selected by config, never hardcoded.
3. **Interrupts are deterministic.** Nodes that call `interrupt()` re-execute from the top of the node on resume. Never call `interrupt()` conditionally or in non-deterministic loops inside a node; side effects before an `interrupt()` must be idempotent.
4. **Typed state everywhere.** Python: Pydantic v2 models / `TypedDict` with reducers for the graph state. TypeScript: a single `types.ts` mirroring the API contracts. The state schema in §5 is the single source of truth — no feature may add/rename state fields without updating §5 first.
5. **Every LLM call goes through the model router** (`app/llm/router.py`, built in F9 but stubbed from F2 with a single default model). Nodes never instantiate model clients directly.
6. **Cost & token tracking is not optional.** Every node records tokens/cost into state via the `usage_log` reducer.
7. **Structured outputs via Pydantic schemas** passed to the model's structured-output API (`.with_structured_output(...)` in LangChain 1.x) — never regex-parse JSON out of prose.
8. **12-factor config.** All secrets/config via environment variables loaded by `pydantic-settings`. Committed `.env.example`, never `.env`.
9. **Observability from day one.** LangSmith tracing enabled via env vars (`LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT=atlas`). All graph runs are traceable.
10. **No AI-boilerplate frontend.** The React app follows the design system in §8. No default Vite splash, no unstyled shadcn dumps, no lorem ipsum, no emoji-as-icons. Every screen must look like a deliberate product (reference quality bar: Linear, Vercel dashboard, LangSmith UI).
11. **Verify library APIs before use.** Claude Code MUST check the locally installed package version (`pip show`, `npm ls`) and, when uncertain about an API, read the package's actual source/types in `node_modules` or site-packages rather than guessing from memory. Library APIs in this spec were verified against docs as of mid-2026, but exact minor versions drift — trust the installed package over memory.

## 3. Tech stack (pinned intent — resolve exact patch versions at install time)

| Layer               | Choice                                                                          | Notes                                                             |
| ------------------- | ------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| Language (backend)  | Python 3.12                                                                     | managed with `uv`                                                 |
| Agent framework     | `langgraph>=1.0,<2.0`                                                           | StateGraph, Send, interrupt, Command                              |
| LLM integration     | `langchain>=1.0,<2.0`, `langchain-openai`                                       | `init_chat_model`; **OpenAI is the sole provider** (`OPENAI_API_KEY`), no Anthropic. Role→model via `MODEL_ROUTING` env (F9) |
| Checkpointing       | `langgraph-checkpoint-sqlite` (dev), `langgraph-checkpoint-postgres` (prod)     | selected via `CHECKPOINT_BACKEND` env                             |
| API                 | FastAPI + Uvicorn                                                               | SSE via `sse-starlette`                                           |
| Validation/config   | Pydantic v2, `pydantic-settings`                                                |                                                                   |
| DB                  | PostgreSQL 16 (Docker)                                                          | checkpoints + run metadata                                        |
| Web search tool     | Tavily (`langchain-tavily`)                                                     | `TAVILY_API_KEY`                                                  |
| Evals               | LangSmith SDK + custom harness; RAGAS only for the RAG tool's retrieval quality |                                                                   |
| Frontend            | **React 19 + TypeScript + Vite**                                                | REQUIRED: React. No Next.js — this is an SPA talking to FastAPI   |
| Frontend state/data | TanStack Query v5 (server state) + Zustand (UI state)                           |                                                                   |
| Styling             | Tailwind CSS v4                                                                 | design tokens in §8; no component library — hand-built components |
| Frontend streaming  | native `EventSource` wrapper for SSE                                            |                                                                   |
| Report rendering    | `react-markdown` + `remark-gfm`                                                 |                                                                   |
| Containerization    | Docker + docker-compose                                                         | multi-stage builds                                                |
| CI                  | GitHub Actions                                                                  | lint, typecheck, tests on PR                                      |

## 4. Repository layout (monorepo — fixed, all features conform to this)

```
atlas/
├── SPEC.md                     # this file
├── docker-compose.yml
├── .github/workflows/ci.yml
├── backend/
│   ├── pyproject.toml          # uv-managed
│   ├── Dockerfile
│   ├── app/
│   │   ├── main.py             # FastAPI app factory
│   │   ├── config.py           # pydantic-settings Settings
│   │   ├── api/
│   │   │   ├── routes_runs.py  # run lifecycle endpoints
│   │   │   └── sse.py          # SSE event translation
│   │   ├── graph/
│   │   │   ├── state.py        # ResearchState — single source of truth
│   │   │   ├── builder.py      # build_graph() -> compiled graph
│   │   │   ├── nodes/
│   │   │   │   ├── planner.py
│   │   │   │   ├── approval.py # interrupt() gate
│   │   │   │   ├── worker.py
│   │   │   │   ├── reviewer.py
│   │   │   │   └── writer.py
│   │   │   └── routing.py      # conditional-edge functions + Send fan-out
│   │   ├── tools/
│   │   │   ├── web_search.py
│   │   │   ├── rag.py          # wraps the user's existing RAG app
│   │   │   └── calculator.py
│   │   ├── llm/
│   │   │   └── router.py       # role->model routing + usage tracking
│   │   ├── persistence/
│   │   │   ├── checkpointer.py # backend-selected checkpointer factory
│   │   │   └── runs_repo.py    # runs metadata table (RunsRepo) — F5
│   │   └── services/
│   │       └── run_service.py  # RunService: run lifecycle (start/resume) — F5, used by the API
│   ├── evals/
│   │   ├── benchmark_topics.jsonl
│   │   ├── run_benchmark.py
│   │   ├── graders.py
│   │   └── report_template.md
│   └── tests/
└── frontend/
    ├── package.json
    ├── Dockerfile
    ├── vite.config.ts
    └── src/
        ├── main.tsx
        ├── App.tsx
        ├── api/                # typed API client + SSE hook
        ├── types.ts            # mirrors backend contracts
        ├── stores/             # zustand
        ├── styles/             # tailwind v4 theme (@theme tokens)
        ├── components/
        │   ├── ui/             # Button, Card, Badge, Spinner, Tabs...
        │   ├── run/            # NodeTimeline, SectionCard, CostMeter
        │   ├── approval/       # PlanApprovalPanel
        │   └── report/         # ReportViewer, SourceList
        └── pages/
            ├── NewRunPage.tsx
            ├── RunPage.tsx
            └── HistoryPage.tsx
```

## 5. Graph state schema — SINGLE SOURCE OF TRUTH

Defined once in `backend/app/graph/state.py`. All features use these exact names.

```python
from typing import Annotated, Literal
from typing_extensions import TypedDict
from pydantic import BaseModel
import operator

class Source(BaseModel):
    url: str
    title: str
    snippet: str          # <=300 chars, our own summary — never long verbatim quotes
    tool: Literal["web_search", "rag", "calculator"]

class SectionPlan(BaseModel):
    id: str               # "s1", "s2", ...
    title: str
    objective: str        # what this section must answer
    suggested_queries: list[str]

class SectionDraft(BaseModel):
    section_id: str
    content_md: str       # markdown with [n] citation markers
    sources: list[Source]
    revision: int         # 0 = first draft

class Review(BaseModel):
    section_id: str
    verdict: Literal["approved", "revise"]
    score: float          # 0-1
    feedback: str         # concrete revision instructions when verdict == "revise"

class UsageEvent(BaseModel):
    node: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float

class ToolCallRecord(BaseModel):          # one per worker tool invocation (F8)
    section_id: str
    tool: Literal["web_search", "rag", "calculator"]
    urls: list[str]       # URLs this call returned; [] for calculator / no results
    contents: dict[str, str]  # url -> full tool-result content the worker read;
                              # groundedness ground truth (grader judges claims against
                              # this, not the 300-char Source.snippet); {} for calculator

class ResearchState(TypedDict):
    topic: str
    plan: list[SectionPlan]
    plan_approved: bool
    drafts: Annotated[list[SectionDraft], operator.add]   # reducer: append (parallel workers)
    reviews: Annotated[list[Review], operator.add]
    revision_counts: dict[str, int]                       # section_id -> revisions used
    final_report_md: str
    usage_log: Annotated[list[UsageEvent], operator.add]
    tool_calls: Annotated[list[ToolCallRecord], operator.add]  # anti-fabrication ground truth + trajectory (F8)
    status: Literal["planning", "awaiting_approval", "researching",
                    "reviewing", "writing", "done", "failed"]
```

**Hard limits (constants in `state.py`):** `MAX_SECTIONS = 6`, `MAX_REVISIONS_PER_SECTION = 2`, `MAX_TOOL_CALLS_PER_WORKER = 8`, `RUN_COST_CEILING_USD = 1.50` (worker aborts gracefully and reports partial results if exceeded).

## 6. Graph topology — fixed

```
START → planner → approval_gate(interrupt) → [Send fan-out] worker×N → reviewer
                                                    ↑                      │
                                                    └── revise (per section, ≤2)
                                                                           │
                                                              all approved ▼
                                                                        writer → END
```

- `planner` → produces `plan`, sets `status="awaiting_approval"`.
- `approval_gate` → calls `interrupt({"plan": plan})`; resume payload is `{"action": "approve"} | {"action": "edit", "plan": [...]}`. Node is trivially idempotent (no side effects before interrupt).
- `fan_out` (conditional edge after approval) → returns `[Send("worker", {"section": s, "topic": topic}) for s in plan]`.
- `reviewer` → grades ALL drafts of the current wave; routing function `route_after_review` returns `Send("worker", ...)` for each `revise` verdict with remaining budget, else routes to `writer` when every section is approved or out of revision budget.
- `writer` → merges approved (or best-available) drafts into `final_report_md` with a deduplicated numbered source list.

## 7. API contract — fixed (backend implements, frontend consumes; do not drift)

```
POST   /api/runs                 {topic}            → 201 {run_id, thread_id}
GET    /api/runs                                    → 200 [{run_id, topic, status, created_at, cost_usd}]
GET    /api/runs/{run_id}                           → 200 RunDetail (full state snapshot + cost_breakdown + trace_id)
POST   /api/runs/{run_id}/resume {action, plan?}    → 202 (resumes an interrupted run)
GET    /api/runs/{run_id}/events                    → SSE stream (see below)
GET    /api/runs/{run_id}/report.md                 → 200 markdown download (implemented in F7)
GET    /api/health                                  → 200 {status:"ok"}
```

`RunDetail` additionally carries `cost_breakdown: {node: cost_usd}` (F9) — the `usage_log`
summed per node, a derived field (never stored in `ResearchState` §5) — and
`trace_id: str | null` (F11), the LangSmith root run id for the run's trace deep-link
(null when `LANGSMITH_TRACING` is off; captured server-side via `collect_runs`, persisted
on the `runs` row). Frontend `types.ts` mirrors both in F11.

**SSE event envelope** (every event is one JSON object, `event:` field set to `type`):

```ts
type AtlasEvent =
  | { type: "status"; status: RunStatus }
  | { type: "node_started"; node: string; section_id?: string }
  | {
      type: "node_finished";
      node: string;
      section_id?: string;
      summary: string;
    }
  | { type: "token"; node: string; delta: string } // writer streaming
  | { type: "interrupt"; payload: { plan: SectionPlan[] } }
  | { type: "usage"; event: UsageEvent; total_cost_usd: number }
  | { type: "review"; review: Review }
  | { type: "done"; report_md: string }
  | { type: "error"; message: string };
```

## 8. Frontend design system (applies to F10–F12)

- **Feel:** calm, dense, technical. Dark-first UI. Reference bar: Linear / LangSmith.
- **Tokens (Tailwind v4 `@theme` in `styles/theme.css`):**
  - Background `#0B0E14`, surface `#131722`, raised surface `#1A2030`, border `#232B3D`.
  - Text primary `#E6EAF2`, secondary `#8A94A8`.
  - Accent `#6E9FFF` (actions/links), success `#4ADE80`, warn `#FBBF24`, danger `#F87171`.
  - Font: Inter (UI) + JetBrains Mono (code/costs/ids). Radius 10px cards / 8px controls. 8-pt spacing grid.
- **Rules:** real empty states (illustration-free, text + one action), skeleton loaders (never spinners for page loads), keyboard submit on forms, visible focus rings, all timestamps relative ("2m ago") with absolute on hover, costs always monospace with 4 decimals.
- **No component library.** `components/ui/` is hand-built on Tailwind. Icons: `lucide-react` only.

## 9. Definition of done (every feature)

- Code typechecks (`mypy` relaxed-strict backend / `tsc --noEmit` frontend) and lints (`ruff` / `eslint`).
- Tests listed in the feature's acceptance criteria pass (`pytest` / `vitest`).
- No secrets in code. `.env.example` updated if new vars introduced.
- `README.md` section for the feature updated (how to run/verify it).
- The demo command listed in the feature's **Verify** block runs successfully.

---

# FEATURES

> Implement strictly in order — each feature assumes all previous ones are merged. Backend: F1–F9. Frontend: F10–F12. Deployment: F13.

---
