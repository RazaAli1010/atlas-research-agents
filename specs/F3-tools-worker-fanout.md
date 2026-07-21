## F3 — Tools & parallel worker fan-out (Send API)

**Goal:** Worker nodes research each planned section in parallel using real tools (web search, RAG, calculator) via the LangGraph `Send` API; their `SectionDraft`s accumulate in `drafts` through the reducer, and the writer mechanically merges them into a cited report with a deduplicated numbered source list.

**Depends on:** F1 (repo scaffold, config, `.env.example`), F2 (`ResearchState`, `build_graph`, `planner`, `writer` stub, `llm/router.py` stub, checkpointer factory, `demo.py`).

---

### Context digest

Everything below is quoted from the current codebase — use these exact names, paths, and shapes. Do **not** re-derive them.

**State (`backend/app/graph/state.py`) — do not add/rename fields:**

```python
class Source(BaseModel):
    url: str
    title: str
    snippet: str          # <=300 chars, our own summary — never long verbatim quotes
    tool: Literal["web_search", "rag", "calculator"]

class SectionPlan(BaseModel):
    id: str               # "s1", "s2", ...   ← NOTE: field is `id`, NOT `section_id`
    title: str
    objective: str
    suggested_queries: list[str]

class SectionDraft(BaseModel):
    section_id: str       # ← matches SectionPlan.id value; field name here is `section_id`
    content_md: str       # markdown with [n] citation markers
    sources: list[Source]
    revision: int         # 0 = first draft

class ResearchState(TypedDict):
    topic: str
    plan: list[SectionPlan]
    plan_approved: bool
    drafts: Annotated[list[SectionDraft], operator.add]   # append reducer (parallel workers)
    reviews: Annotated[list[Review], operator.add]
    revision_counts: dict[str, int]
    final_report_md: str
    usage_log: Annotated[list[UsageEvent], operator.add]
    status: Literal["planning","awaiting_approval","researching","reviewing","writing","done","failed"]
```

**Constants (`state.py`):** `MAX_SECTIONS = 6`, `MAX_TOOL_CALLS_PER_WORKER = 8`, `RUN_COST_CEILING_USD = 1.50`, `MAX_REVISIONS_PER_SECTION = 2`.

**Model router (`backend/app/llm/router.py`) — the only way to get a model / record cost:**
- `get_model(role: Role) -> BaseChatModel` where `Role = Literal["planner","worker","reviewer","writer"]`. Returns a `BaseChatModel`; call `.bind_tools(tools)` on it (§2.5 — never instantiate a client directly).
- `track_usage(node: str, response: AIMessage) -> UsageEvent` — reads `response.usage_metadata` / `response_metadata["model_name"]`, prices from `MODEL_PRICES`, returns a `UsageEvent`. Every model call the worker makes must append its `track_usage(...)` result to `usage_log`.

**Config (`backend/app/config.py`):** `Settings(BaseSettings)` with required `OPENAI_API_KEY`, `TAVILY_API_KEY`; optional `DEFAULT_MODEL="openai:gpt-4o-mini"`, etc. Module singleton `settings`. Precedent (from router): pydantic-settings loads keys into `settings` but does **not** export them to `os.environ`, so SDKs that read env (Tavily) must be handed the key explicitly.

**Builder (`backend/app/graph/builder.py`) — current topology is `START → planner → writer → END`.** This feature rewires it (see Scope 4). The approval interrupt is **not** part of F3 (later feature); wire `planner → fan_out → worker×N → writer`.

**Writer stub (`backend/app/graph/nodes/writer.py`):** currently concatenates plan + drafts into `final_report_md`, sets `status="done"`. F3 upgrades it to a real mechanical merge (Scope 3). Full LLM synthesis stays deferred to a later feature.

**Engineering principles that bind this feature:** §2.1 LangGraph 1.x only, no `langgraph.prebuilt`, no prebuilt agent constructors — the worker loop is hand-written. §2.5 all model calls via the router. §2.6 cost/tokens recorded into `usage_log` on every call. §2.7 structured outputs via Pydantic, never regex-parse JSON out of prose. §2.11 verify installed APIs.

**API/SSE contract:** unchanged by F3 (no new routes/events). `node_started`/`node_finished` with `section_id` already exist in the envelope for later wiring — F3 does not implement SSE.

---

### Context deltas

**One delta — add a new optional config var (edit these before implementing):**

1. `backend/app/config.py` — add to `Settings`:
   ```python
   RAG_SERVICE_URL: str | None = None   # existing RAG app HTTP base; unset → rag tool self-disables
   ```
2. `.env.example` (repo root) — add under a new `# --- RAG retriever tool (optional) ---` block:
   ```
   # RAG_SERVICE_URL=http://localhost:8100
   ```
   Leave it commented so the default (unset → tool disabled) is the out-of-box behavior.

No state-schema, route, or constant changes. `Source.tool` already includes all three tool names.

---

### Scope

#### 1. Tools (`backend/app/tools/`) — each a `@tool` from `langchain.tools` with a rich docstring

The docstring is the tool's LLM-facing contract (the model reads it to decide when to call) — write it as such: one line purpose, when to use, args, and what it returns.

**`web_search.py` — `web_search(query: str) -> list[dict]`**
- Wrap `langchain_tavily.TavilySearch` (verified export, v0.2.18). `TavilySearch` reads `TAVILY_API_KEY` from the environment and config does not export it, so set it once at module import: `os.environ.setdefault("TAVILY_API_KEY", settings.TAVILY_API_KEY)`.
- Instantiate `TavilySearch(max_results=5)`. Inside the `@tool`, call `_client.invoke({"query": query})`; Tavily returns `{"results": [{"title","url","content",...}], ...}`.
- Normalize to `[{"url","title","content"}]`, truncating `content` to **1,000 chars** each. On zero results return `[]`. Catch client/network exceptions and return `[]` (graceful degradation — the worker notes the gap; see AC-3).

**`rag.py` — `rag_search(query: str) -> list[dict]`**
- HTTP GET/POST against `settings.RAG_SERVICE_URL` (e.g. `POST {RAG_SERVICE_URL}/search {"query": query}`) using `httpx` (already a dev dep; add to runtime deps if the import is used in app code — see Implementation notes). Timeout ≤ 10s. Normalize to `[{"url","title","content"}]` (content truncated to 1,000 chars); on error/timeout return `[]`.
- **Self-disabling registration:** export a module function `rag_tool_or_none()` that returns the `@tool` object only when `settings.RAG_SERVICE_URL` is set, else logs `logging.getLogger(__name__).warning(...)` once and returns `None`. The graph must run with it unset (AC-3).

**`calculator.py` — `calculator(expression: str) -> str`**
- Safe arithmetic via `ast` — **no `eval`/`exec`**. Parse with `ast.parse(expression, mode="eval")` and walk the tree, allowing only: `ast.Expression`, `ast.BinOp`, `ast.UnaryOp`, `ast.Constant` (numbers only), and operators `Add, Sub, Mult, Div, FloorDiv, Mod, Pow, USub, UAdd`. Any other node (`Name`, `Call`, `Attribute`, `Subscript`, dunder access, string constants) → raise/return a clear `"Error: unsupported expression"`. Cap `Pow` exponent (e.g. reject exponent > 100) to prevent CPU blowups.
- Rejecting `__import__("os")`, `().__class__`, function calls, and attribute access is a hard requirement (AC / test).

**`tools/__init__.py` — `get_worker_tools() -> list[BaseTool]`**
- Assemble the enabled toolset: always `web_search`, `calculator`; append `rag_search` only if `rag_tool_or_none()` returns non-None. This is the single source the worker binds. Also expose `TOOL_NAME_TO_SOURCE_TOOL` mapping tool `.name` → the `Source.tool` literal (`"web_search"|"rag"|"calculator"`) so the worker can tag sources.

#### 2. Worker node (`backend/app/graph/nodes/worker.py`) — explicit, bounded ReAct loop

Signature `def worker(payload: dict) -> dict:` — receives the `Send` payload merged with state. Payload keys: `section` (`SectionPlan`), `topic` (`str`), and optionally `feedback` (`str`) + `previous_draft` (`SectionDraft`) for revision mode (Scope 5). Read accumulated cost from the merged state's `usage_log`.

Loop shape (hand-written — no `create_react_agent`, no `ToolNode`):

```python
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

def worker(payload: dict) -> dict:
    section: SectionPlan = payload["section"]
    topic: str = payload["topic"]
    tools = get_worker_tools()
    tools_by_name = {t.name: t for t in tools}

    accrued = sum(e.cost_usd for e in payload.get("usage_log", []))
    cost_capped = accrued >= RUN_COST_CEILING_USD   # skip tools, draft from context only

    messages = _build_messages(section, topic, payload)   # revision-aware (Scope 5)
    model = get_model("worker").bind_tools(tools)

    usage: list[UsageEvent] = []
    collected: list[Source] = []
    calls = 0

    while True:
        ai: AIMessage = model.invoke(messages)
        usage.append(track_usage("worker", ai))
        messages.append(ai)
        if cost_capped or not ai.tool_calls or calls >= MAX_TOOL_CALLS_PER_WORKER:
            break
        for tc in ai.tool_calls:
            if calls >= MAX_TOOL_CALLS_PER_WORKER:
                break
            calls += 1
            result = tools_by_name[tc["name"]].invoke(tc["args"])   # structured return in hand
            collected += _to_sources(tc["name"], result)            # map dicts → Source
            messages.append(ToolMessage(content=_summarize(result), tool_call_id=tc["id"]))

    content_md = _final_answer_from(messages)   # last AIMessage text; ensure [n] markers present
    draft = SectionDraft(
        section_id=section.id,
        content_md=_ensure_citation_note(content_md, collected, cost_capped, tools),
        sources=_dedup(collected),
        revision=(payload["previous_draft"].revision + 1) if payload.get("previous_draft") else 0,
    )
    return {"drafts": [draft], "usage_log": usage, "status": "researching"}
```

Rules:
- **Tool-call cap:** total tool invocations ≤ `MAX_TOOL_CALLS_PER_WORKER` (8) — enforced by `calls` counter across all model turns, not per turn (AC-1).
- **Cost ceiling:** if `accrued >= RUN_COST_CEILING_USD`, bind is skipped / loop breaks after the first (toolless) model turn and the draft `content_md` is flagged (e.g. a leading `> _Note: run cost ceiling reached; drafted from context without tool research._`).
- **Citations:** the worker system prompt instructs the model to cite every factual claim with `[n]` markers indexed into the sources it was given / gathered, and to end with nothing extra. `sources` on the draft is the ordered, de-duplicated (by URL, and for calculator by expression) list the `[n]` resolve against. Assign `n` = 1-based index into the final `sources` list; if the model emitted markers, keep them consistent (simplest: number sources in first-seen order and instruct the model to reference "source k" as `[k]`). Include an inline `_to_sources` that tags each with the correct `Source.tool` value and writes a ≤300-char `snippet` (our summary of `content`, truncated — never a long verbatim quote, §5).
- **Graceful degradation:** if every tool returns `[]` (no web results, RAG disabled), the worker still produces a draft whose `content_md` states the gap explicitly (e.g. "No external sources were retrievable for this section.") and `sources` is `[]` (AC-3).
- Returns `status="researching"`.

#### 3. Writer node (`backend/app/graph/nodes/writer.py`) — real mechanical merge

Replace the F2 concatenation with a deterministic merge (no LLM in F3):
- Iterate `plan` in order; for each `SectionPlan.id` pull its `SectionDraft` from `drafts` (a dict `{d.section_id: d}`; if multiple drafts share an id — a revised section — keep the one with the highest `revision`).
- Build a **global** deduplicated source list (dedup by `Source.url`; calculator sources keyed by their expression string). Renumber each section's local `[n]` markers to the global index with a regex remap: for each draft, map its local source position → global position and `re.sub(r"\[(\d+)\]", ...)` over `content_md`.
- Emit `# {topic}`, then `## {i}. {title}` + remapped section body per section, then a final `## Sources` list: `1. [title](url)` per unique source (calculator sources rendered as `computed value` lines). Set `final_report_md`, `status="done"`.
- Put the merge logic in a testable helper `merge_drafts(plan: list[SectionPlan], drafts: list[SectionDraft]) -> tuple[str, list[Source]]` in `writer.py` (or `graph/routing.py` if you prefer, but keep it importable for unit tests).

#### 4. Routing & wiring (`backend/app/graph/routing.py`, `builder.py`)

`routing.py`:
```python
from langgraph.types import Send   # verified location in langgraph 1.2.9

def fan_out(state: ResearchState) -> list[Send]:
    topic = state["topic"]
    base_usage = state.get("usage_log", [])
    return [
        Send("worker", {"section": s, "topic": topic, "usage_log": base_usage})
        for s in state["plan"]
    ]
```
- One `Send("worker", ...)` per section in `plan`; payload carries `section`, `topic`, and a `usage_log` snapshot so each worker can read accrued cost. (Revision routing — resending with `feedback`/`previous_draft` — is F4; do not add it here.)

`builder.py` — new topology `START → planner → (fan_out) worker×N → writer → END`:
```python
graph.add_node("planner", planner)
graph.add_node("worker", worker)
graph.add_node("writer", writer)
graph.add_edge(START, "planner")
graph.add_conditional_edges("planner", fan_out, ["worker"])
graph.add_edge("worker", "writer")     # worker → writer fan-in via reducer
graph.add_edge("writer", END)
```
- Use `add_conditional_edges("planner", fan_out, ["worker"])` (the path-map third arg lists possible targets for LangGraph 1.x). The `drafts`/`usage_log` reducers fan the parallel workers back into one state at `writer`.

#### 5. Worker revision mode (build the code path now; F4 wires the routing)

Inside `_build_messages(section, topic, payload)`: when `payload` contains both `feedback: str` and `previous_draft: SectionDraft`, switch the system/human prompt to revision instructions — "Here is your previous draft and the reviewer's feedback; produce an improved draft addressing every point, keeping valid citations." The resulting `SectionDraft.revision = previous_draft.revision + 1`. First-draft mode (no feedback) uses `revision = 0`. F4 will populate these payload keys from `route_after_review`; F3 only implements and unit-tests the branch.

---

### Out of scope

- **Approval interrupt gate** (`planner → approval_gate(interrupt) → fan_out`) — later HITL feature. F3 wires `planner → fan_out` directly.
- **Reviewer node and revision routing** (`reviewer`, `route_after_review`, resending `Send` with feedback) — F4. F3 builds and tests the worker's revision *code path* but does not wire the loop.
- **LLM synthesis in the writer** (narrative rewriting/summarizing of merged drafts) — later feature. F3's writer is a mechanical merge.
- **SSE emission** of `node_started`/`node_finished`/`review` events — API feature. F3 changes no routes.
- **Model router role differentiation** — F9. F3 uses `get_model("worker")` which currently returns the single default model.

---

### Implementation notes

- **Verified versions (installed):** `langgraph 1.2.9`, `langchain 1.3.14`, `langchain-core 1.5.0`, `langchain-tavily 0.2.18`, `langchain-openai 1.3.5`, Python 3.12.
- **Imports (verified):** `from langchain.tools import tool` (present) or equivalently `from langchain_core.tools import tool`; `from langchain_tavily import TavilySearch`; `from langgraph.types import Send`; messages from `langchain_core.messages`. Do **not** import from `langgraph.prebuilt` (§2.1).
- **`Send` payload merges with state:** a node reached via `Send` receives the payload dict; to also read accrued `usage_log` the fan-out passes it explicitly (above) rather than relying on full-state injection — keeps the worker signature a plain dict and the cost read deterministic.
- **httpx as runtime dep:** it's currently only in the `dev` group. If `rag.py` imports it in app code, add `httpx` to `[project].dependencies` in `backend/pyproject.toml` (and run `uv sync`). The rag tool is optional, so guard the import inside `rag_tool_or_none()` if you want to avoid a hard runtime dependency.
- **Determinism / idempotency:** the worker must be safe to re-run from the top (future interrupt/resume). It has no side effects before producing its draft; all randomness is inside the model call. Do not read wall-clock or mutate module globals per call (the Tavily client is a module singleton, read-only).
- **Tool-call cap is a hard ceiling, not a target** — count every `tools_by_name[...].invoke(...)`, break the outer loop when reached even if the model still requests tools.
- **Citations must resolve:** never emit an `[n]` with no matching entry in `sources`. When trimming/deduping sources, remap markers so no dangling index remains (writer's regex remap + worker-side numbering).
- **Snippets:** `Source.snippet` ≤ 300 chars and is *our* summary/truncation of tool content — never a long verbatim quote (§5).
- **No `eval`/`exec` anywhere in `calculator.py`** — `ast`-walk only; this is explicitly tested.
- **`.with_structured_output` is not used by the worker** — the worker uses `.bind_tools` and a free-form final answer; structured output is the planner/reviewer pattern. That's intended and consistent with §2.7 (structured output is for extracting typed data, not for the tool-loop's prose answer).

---

### Test plan

New tests under `backend/tests/` (pytest; follow `conftest.py` patterns, use a fake/stub chat model — no live OpenAI/Tavily calls):

1. `test_routing_fanout.py` — `fan_out(state)` with a 4-section plan returns exactly 4 `Send` objects, each `.node == "worker"`, each payload carrying its own `section` and the shared `topic`.
2. `test_worker_reducer.py` — invoke the graph (or the worker node directly) N times with a **fake model** that emits a fixed final answer + fixed tool calls; assert all N `SectionDraft`s land in `drafts` (reducer/`operator.add` proof) and `section_id`s match the plan ids.
3. `test_worker_tool_cap.py` — fake model that requests a tool on every turn; assert the worker stops at ≤ `MAX_TOOL_CALLS_PER_WORKER` tool invocations (spy/counter on the tool) and still returns a draft.
4. `test_worker_cost_ceiling.py` — seed payload `usage_log` whose summed `cost_usd ≥ RUN_COST_CEILING_USD`; assert the worker makes **zero** tool calls and the draft `content_md` carries the cost-ceiling flag.
5. `test_worker_revision_mode.py` — payload with `feedback` + `previous_draft(revision=0)`; assert the prompt path switches (revision instructions present) and returned draft has `revision == 1`.
6. `test_calculator.py` — `calculator("2 + 3 * 4") == "14"`; `calculator("(100/12)*1.2")` correct; `calculator('__import__("os").system("echo hi")')`, `calculator("().__class__")`, and `calculator("2 ** 9999")` all return an error string / raise and never execute.
7. `test_web_search_normalize.py` — monkeypatch the Tavily client's `.invoke` to return canned results; assert output is `[{"url","title","content"}]` with `content` truncated to ≤1,000 chars; empty results → `[]`.
8. `test_rag_disabled.py` — with `RAG_SERVICE_URL` unset, `get_worker_tools()` excludes `rag_search` and a warning is logged; the graph still builds and runs.
9. `test_writer_merge.py` — `merge_drafts(plan, drafts)` with two sections whose drafts have overlapping source URLs: assert one deduplicated global `## Sources` list, `[n]` markers remapped to global indices, sections emitted in plan order, and no dangling citation index.
10. `test_graph_degraded.py` — fake model + tools all returning `[]` (Tavily zero results, RAG unset): graph reaches `status=="done"`, report has a `## Sources` section (possibly empty), and each section body notes the source gap.

---

### Verify

```bash
cd backend
uv sync
uv run ruff check . && uv run mypy app && uv run pytest -q
# Real end-to-end (needs OPENAI_API_KEY + TAVILY_API_KEY in backend/.env):
uv run python -m app.graph.demo "Compare vector database pricing for a seed-stage startup"
```
Expected: ruff/mypy clean; all pytest tests pass. The demo prints a multi-section Markdown report where every section carries `[n]` markers and the report ends with a `## Sources` list. With `LANGSMITH_TRACING=true`, the LangSmith `atlas` project shows one run whose worker branches execute in parallel (overlapping timestamps).

### Acceptance criteria

- [ ] `fan_out` returns exactly N `Send("worker", …)` for an N-section plan; workers run in parallel (LangSmith trace timestamps overlap) and each makes ≤ `MAX_TOOL_CALLS_PER_WORKER` (8) tool calls (tests 1, 3).
- [ ] All parallel drafts accumulate in `drafts` via the reducer with correct `section_id`s (test 2).
- [ ] Every factual claim in a draft carries an `[n]` marker resolvable to an entry in that draft's `sources`; the final report ends with a `## Sources` list and the writer remaps section markers to global indices with no dangling index (tests 9, 10; demo).
- [ ] The worker aborts tool use and drafts from context (flagged in `content_md`) when accrued cost ≥ `RUN_COST_CEILING_USD` (test 4).
- [ ] Revision code path: payload with `feedback` + `previous_draft` yields a draft with `revision` incremented and revision-mode prompt (test 5).
- [ ] `calculator` computes arithmetic and rejects `__import__`/attribute/call/oversized-power inputs with no code execution (test 6).
- [ ] Graph completes (`status=="done"`) with `RAG_SERVICE_URL` unset **and** Tavily returning zero results; affected sections note the source gap (tests 8, 10; AC-3).
- [ ] `ruff`, `mypy app`, and `pytest` all pass; `.env.example` and `config.py` updated with `RAG_SERVICE_URL` (Context deltas).
