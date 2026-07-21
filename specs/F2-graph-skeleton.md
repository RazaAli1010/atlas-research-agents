## F2 — Graph state, planner node & walking skeleton graph

**Goal:** A typed `ResearchState` schema plus a minimal compiled graph (`START → planner → writer → END`) that produces a stub report from a topic, proving the LangGraph state/router/checkpointer plumbing end-to-end before real research complexity arrives.

**Depends on:** F1 (monorepo scaffold, `config.py` Settings, `pyproject.toml` deps, `.env.example`).

---

### Context digest

Exact contracts this feature must conform to (from CLAUDE.md / SPEC):

**State schema (§5) — `backend/app/graph/state.py`, single source of truth.** Implement verbatim:

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
    feedback: str

class UsageEvent(BaseModel):
    node: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float

class ResearchState(TypedDict):
    topic: str
    plan: list[SectionPlan]
    plan_approved: bool
    drafts: Annotated[list[SectionDraft], operator.add]
    reviews: Annotated[list[Review], operator.add]
    revision_counts: dict[str, int]
    final_report_md: str
    usage_log: Annotated[list[UsageEvent], operator.add]
    status: Literal["planning", "awaiting_approval", "researching",
                    "reviewing", "writing", "done", "failed"]
```

**Constants (§5) — live in `state.py`:** `MAX_SECTIONS = 6`, `MAX_REVISIONS_PER_SECTION = 2`, `MAX_TOOL_CALLS_PER_WORKER = 8`, `RUN_COST_CEILING_USD = 1.50`.

**Engineering principles that bind this feature (§2):**
- LangGraph 1.x APIs only; **never** import from `langgraph.prebuilt` (moved to `langchain.agents`).
- A checkpointer is mandatory for the compiled graph; backend selected by `CHECKPOINT_BACKEND` env, never hardcoded (`sqlite` dev / `postgres` prod).
- Every LLM call goes through the model router (`app/llm/router.py`); nodes never instantiate model clients directly.
- Cost/token tracking is mandatory — every node appends a `UsageEvent` via the `usage_log` reducer.
- Structured outputs via Pydantic schemas passed to `.with_structured_output(...)` — never regex/`json.loads` on prose.
- Typed state everywhere; §5 is the single source of truth.

**Config already in place (F1, `app/config.py`):** `OPENAI_API_KEY` (required), `TAVILY_API_KEY` (required), `LANGSMITH_API_KEY`, `LANGSMITH_TRACING`, `LANGSMITH_PROJECT="atlas"`, `DATABASE_URL`, `CHECKPOINT_BACKEND: Literal["sqlite","postgres"]="sqlite"`, `CORS_ORIGINS`.

**Router signatures (final, internals replaced in F9):**
- `get_model(role: Literal["planner","worker","reviewer","writer"]) -> BaseChatModel`
- `track_usage(node: str, response: AIMessage) -> UsageEvent`

**Repo layout (§4) — files this feature creates/fills:** `app/graph/state.py`, `app/llm/router.py`, `app/graph/nodes/planner.py`, `app/graph/nodes/writer.py`, `app/graph/builder.py`, `app/persistence/checkpointer.py`, plus a new `app/graph/demo.py`.

---

### Context deltas

These require editing the shared context (CLAUDE.md) **before/with** implementation:

1. **LLM provider conflict — MUST resolve.** The F2 feature text proposes default model `anthropic:claude-sonnet-4-6`. This directly contradicts §3 ("OpenAI is the sole provider (`OPENAI_API_KEY`), no Anthropic") and the F1 `config.py`/`.env.example`, which carry only `OPENAI_API_KEY`. **Resolution (chosen): default to an OpenAI model.** Use `DEFAULT_MODEL = "openai:gpt-4o-mini"` (implementer confirms a current, available OpenAI chat model id at install time per §2.11). Do **not** wire Anthropic. If the user actually wants Anthropic, that is a change to §3 and F1 config — flag before proceeding.

2. **New env var `DEFAULT_MODEL`.** Add to `app/config.py` Settings as `DEFAULT_MODEL: str = "openai:gpt-4o-mini"` and to `.env.example` (`DEFAULT_MODEL=openai:gpt-4o-mini`). The router reads it via `settings.DEFAULT_MODEL` (not `os.environ` directly), keeping 12-factor config centralized (§2.8). This is an additive delta — note it in §3/§5 config notes.

3. **`MODEL_PRICES` table location.** A `MODEL_PRICES: dict[str, ModelPrice]` lives in `app/llm/router.py` (per-1M-token input/output USD). This is an implementation detail introduced here; F9 may relocate it but the `track_usage` signature stays. No SPEC edit required beyond noting it exists.

---

### Scope

1. **`app/graph/state.py`** — implement §5 verbatim (models + `ResearchState` TypedDict + the four constants). No extra fields, no renames. Keep `operator.add` reducers on `drafts`, `reviews`, `usage_log`.

2. **`app/llm/router.py`** (stub, signatures final):
   - `MODEL_PRICES`: `dict[str, tuple[float, float]]` or small dataclass keyed by bare model id (e.g. `"gpt-4o-mini"`) → (input_usd_per_1M, output_usd_per_1M). Include at least the `DEFAULT_MODEL`'s id.
   - `get_model(role)` — ignores `role` in F2; returns a single cached `init_chat_model(settings.DEFAULT_MODEL)`. Import: `from langchain.chat_models import init_chat_model`. Cache the instance (module-level or `functools.lru_cache`) so repeated calls don't re-init.
   - `track_usage(node, response)` — read `response.usage_metadata` (a `langchain_core.messages.ai.UsageMetadata` TypedDict with `input_tokens`/`output_tokens`/`total_tokens`; may be `None` → treat as 0). Resolve the model id from `response.response_metadata.get("model_name")` or fall back to the configured default; compute `cost_usd` from `MODEL_PRICES` (`input_tokens/1e6*in + output_tokens/1e6*out`), unknown model → cost 0.0. Return a `UsageEvent`.

   ```python
   def get_model(role: Literal["planner","worker","reviewer","writer"]) -> BaseChatModel: ...
   def track_usage(node: str, response: AIMessage) -> UsageEvent: ...
   ```

3. **`app/graph/nodes/planner.py`** — `def planner(state: ResearchState) -> dict`:
   - Define `class PlannerOutput(BaseModel): sections: list[SectionPlan]` **in this module** (wrapper for structured output).
   - Build a prompt from `state["topic"]` instructing 3–6 sections, each with `id` (`s1..sN`), `title`, `objective`, `suggested_queries`.
   - `model = get_model("planner").with_structured_output(PlannerOutput, include_raw=True)` — **`include_raw=True` is required** so token usage is reachable (see Implementation notes). Invoke → `result["parsed"]` is the `PlannerOutput`, `result["raw"]` is the `AIMessage`.
   - Clamp: `sections = result["parsed"].sections[:MAX_SECTIONS]`; re-id sequentially (`s1..`) so ids stay canonical after clamping.
   - Return `{"plan": sections, "status": "awaiting_approval", "usage_log": [track_usage("planner", result["raw"])]}`. (F2 has no interrupt; `status` is set here and the skeleton proceeds straight to writer.)

4. **`app/graph/nodes/writer.py`** (stub) — `def writer(state: ResearchState) -> dict`:
   - Build `final_report_md` from `state["plan"]`: an `# {topic}` H1 then one `## {n}. {title}` per section with its `objective` as a line beneath. If `state.get("drafts")` is non-empty, append each draft's `content_md` under its section (forward-compatible; empty in F2).
   - Return `{"final_report_md": md, "status": "done"}`. No LLM call in F2 → no `UsageEvent`.

5. **`app/graph/builder.py`** — `def build_graph(checkpointer: BaseCheckpointSaver | None = None) -> CompiledStateGraph`:
   - `g = StateGraph(ResearchState)`; add nodes `"planner"`, `"writer"`; edges `START→planner`, `planner→writer`, `writer→END`.
   - `return g.compile(checkpointer=checkpointer)`. Imports: `from langgraph.graph import StateGraph, START, END`.

6. **`app/persistence/checkpointer.py`** — factory selecting by `settings.CHECKPOINT_BACKEND`:
   - `sqlite`: `from langgraph.checkpoint.sqlite import SqliteSaver` — `SqliteSaver.from_conn_string(path)` is a **context manager** (`Iterator[SqliteSaver]`); call `.setup()` once after entering.
   - `postgres`: `from langgraph.checkpoint.postgres import PostgresSaver` — `PostgresSaver.from_conn_string(settings.DATABASE_URL)`, `.setup()` once.
   - Expose `@contextmanager def checkpointer_cx() -> Iterator[BaseCheckpointSaver]` that yields the setup checkpointer (both backends need their connection kept open for the graph's lifetime — do not exit the CM while the graph is in use). The demo and tests use `with checkpointer_cx() as cp:`.

7. **`app/graph/demo.py`** — tiny CLI (`python -m app.graph.demo "<topic>"`):
   - Read topic from `sys.argv[1]`. Enable LangSmith if `settings.LANGSMITH_TRACING` (set `LANGSMITH_*` env from settings before building the graph so the trace is captured).
   - `with checkpointer_cx() as cp:` build graph, `graph.invoke({"topic": topic, ...seed empty state...}, config={"configurable": {"thread_id": <uuid4>}})`.
   - Print the plan outline (titles) and `total_cost = sum(e.cost_usd for e in state["usage_log"])` formatted monospace-style with 4 decimals. Seed state keys that lack defaults (`plan=[]`, `drafts=[]`, `reviews=[]`, `revision_counts={}`, `final_report_md=""`, `usage_log=[]`, `plan_approved=False`, `status="planning"`).

---

### Out of scope

- `interrupt()` / approval gate — **F5** (`nodes/approval.py`).
- `Send` fan-out, worker node, tools (web_search/rag/calculator) — **F3/F4**.
- Reviewer node + `route_after_review` revision routing — **F4**.
- Real LLM-synthesized writer (merging drafts + dedup citations) — **F5**.
- Role-differentiated model routing + real pricing/rate-limit logic in `router.py` — **F9** (only the two signatures are frozen here).
- API endpoints, SSE, runs repo — **F6+**.

---

### Implementation notes

- **Verified versions (uv.lock):** `langgraph==1.2.9`, `langchain==1.3.14`, `langchain-core==1.5.0`, `langchain-openai==1.3.5`, `langgraph-checkpoint-sqlite==3.1.0`, `langgraph-checkpoint-postgres==3.1.0`, `langsmith==0.10.9`.
- **`init_chat_model` import path:** `from langchain.chat_models import init_chat_model` (verified in `langchain/chat_models/base.py`). Accepts `"openai:gpt-4o-mini"` provider-prefixed strings.
- **CRITICAL — structured output + usage:** `.with_structured_output(Schema)` returns the parsed Pydantic object **only**, so `usage_metadata` is unreachable. Use `.with_structured_output(Schema, include_raw=True)` → returns `{"raw": AIMessage, "parsed": Schema, "parsing_error": ...}`; pass `result["raw"]` to `track_usage`. Without this, `usage_log` will be empty and an acceptance test fails.
- **`usage_metadata` shape:** `langchain_core.messages.ai.UsageMetadata` is a TypedDict with `input_tokens`, `output_tokens`, `total_tokens` (int). It is `AIMessage.usage_metadata`, `None` when the provider didn't report usage — guard for `None`.
- **Checkpointer CMs:** `SqliteSaver.from_conn_string(...)` and `PostgresSaver.from_conn_string(...)` both return context managers and expose `.setup()` (verified in the installed packages). Sqlite `":memory:"` is per-connection — for tests prefer `MemorySaver` (`from langgraph.checkpoint.memory import MemorySaver`) or a temp file path; a `":memory:"` sqlite conn closed between calls loses state.
- **No `langgraph.prebuilt` imports** anywhere (acceptance criterion). Use `StateGraph`, `START`, `END` from `langgraph.graph`.
- **Determinism:** planner is a single LLM call with no side effects before returning — fine for F2. Keep it side-effect-free so F5 can wrap it behind an interrupt unchanged.
- **mypy relaxed-strict / ruff** must pass (§9). `ResearchState` is a `TypedDict`; node return dicts are partial updates (LangGraph merges via reducers) — annotate returns as `dict` or a partial `TypedDict` to satisfy mypy.

---

### Test plan

`backend/tests/` (pytest), each test one behavior:

1. `test_state_reducers.py` — two `ResearchState` partial updates each contributing one `SectionDraft` to `drafts` (simulating parallel branches) merge to a length-2 list via `operator.add`; same for `usage_log`. (Can test the reducer directly or via a tiny 2-node graph.)
2. `test_planner.py` — mock `get_model` (monkeypatch to return a fake whose `.with_structured_output(...).invoke(...)` yields `{"raw": AIMessage(..., usage_metadata={...}), "parsed": PlannerOutput(sections=[7 sections])}`); assert planner output `plan` length `== MAX_SECTIONS` (clamped from 7), ids are `s1..s6`, and one `UsageEvent` appended.
3. `test_graph_invoke.py` — `build_graph(MemorySaver())`, invoke with a seeded topic and a mocked planner model; assert `final_report_md` is non-empty, contains the topic H1 and each section title, `status == "done"`, and `len(usage_log) >= 1`.
4. `test_track_usage.py` — feed an `AIMessage` with known `usage_metadata` + `response_metadata.model_name`; assert `UsageEvent.cost_usd` equals the hand-computed value from `MODEL_PRICES`; unknown model → `0.0`.
5. `test_checkpointer_factory.py` — `CHECKPOINT_BACKEND="sqlite"` (temp file) yields a `SqliteSaver` and a graph compiles + invokes with it producing `final_report_md`. (Postgres path may be import-only / skipped without a DB.)

No test may assert on `json.loads` of raw model text — structured output only.

---

### Verify

```
cd backend
uv run python -m app.graph.demo "Compare vector database pricing for a startup"
```

Expected: prints a 3–6 item plan outline (section titles) and a total cost line formatted with 4 decimals (e.g. `total_cost_usd: 0.0003`). With `LANGSMITH_TRACING=true` + a valid `LANGSMITH_API_KEY`, the run appears in the LangSmith `atlas` project showing named nodes `planner` and `writer`.

```
cd backend && uv run pytest && uv run ruff check . && uv run mypy app
```

Expected: all tests pass, no lint/type errors.

---

### Acceptance criteria

- [ ] `state.py` matches §5 verbatim (models, `ResearchState`, and the four constants); no added/renamed fields.
- [ ] Graph compiles and `invoke` succeeds with **both** `MemorySaver` and the sqlite checkpointer, producing a non-empty `final_report_md` and `status == "done"`.
- [ ] `usage_log` is non-empty after a run (planner appends a `UsageEvent`) — proving structured-output usage capture via `include_raw=True`.
- [ ] Planner returns `len(plan) <= MAX_SECTIONS` with a mocked model (7 → clamped to 6, ids re-sequenced `s1..s6`).
- [ ] No import of `langgraph.prebuilt` anywhere (`grep -r "langgraph.prebuilt" app` returns nothing).
- [ ] No `json.loads` on raw model text in `app/graph/nodes/` (structured output only).
- [ ] `get_model` / `track_usage` signatures match §2 exactly; nodes call the router, never `init_chat_model`/model clients directly.
- [ ] `DEFAULT_MODEL` resolves to an OpenAI model (no Anthropic wiring); added to `config.py` Settings and `.env.example`.
- [ ] The Verify demo command runs and prints the plan outline + 4-decimal total cost; a LangSmith trace shows named nodes `planner` and `writer`.
