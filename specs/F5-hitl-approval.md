## F5 — Human-in-the-loop approval gate (interrupt + Command resume)

**Goal:** After planning, the graph pauses at an `interrupt()`, persists via the checkpointer, and resumes with the human's approve/edit decision — surviving a full process restart — while a `runs` metadata row tracks the lifecycle `planning → awaiting_approval → researching → done`.

**Depends on:** F1 (config, `.env`, FastAPI app), F2 (`ResearchState`, `planner`, `build_graph`, `checkpointer_cx`, demo), F3 (worker fan-out, `fan_out`), F4 (reviewer loop, `route_after_review`, writer setting `status="done"`).

---

### Context digest

Exact contracts this feature touches (do not restate with different names):

- **State fields** (`app/graph/state.py`, §5 — single source of truth):
  `topic: str`, `plan: list[SectionPlan]`, `plan_approved: bool`, `status` (Literal incl. `"planning" | "awaiting_approval" | "researching" | ... | "done" | "failed"`), `usage_log: Annotated[list[UsageEvent], operator.add]`.
  `SectionPlan = {id: str, title: str, objective: str, suggested_queries: list[str]}`.
  `UsageEvent = {node, model, input_tokens, output_tokens, cost_usd}`.
  Constant **`MAX_SECTIONS = 6`** lives in `state.py` and is already imported by `planner`.
- **Current graph wiring** (`app/graph/builder.py`) — the line this feature changes:
  ```python
  graph.add_edge(START, "planner")
  graph.add_conditional_edges("planner", fan_out, ["worker"])   # ← F5 inserts approval_gate between these
  ```
- **`fan_out(state) -> list[Send]`** (`app/graph/routing.py`) — already returns one `Send("worker", {...})` per `state["plan"]` section; F5 reuses it unchanged, just re-anchored onto `approval_gate`.
- **`planner`** already sets `status="awaiting_approval"` and produces `plan` (re-ided `s1..sN`, clamped to `MAX_SECTIONS`). **`writer`** already returns `status="done"`.
- **Checkpointer factory** (`app/persistence/checkpointer.py`): `checkpointer_cx()` is a `@contextmanager` yielding a backend-selected saver (`SqliteSaver` when `settings.CHECKPOINT_BACKEND=="sqlite"`, file at module constant `SQLITE_PATH = "atlas_checkpoints.sqlite"`; `PostgresSaver` otherwise). Connection is only valid **inside** the `with`.
- **Engineering principles that bind F5:**
  §2.1 LangGraph 1.x only — import `interrupt`, `Command` from `langgraph.types` (verified below); never `langgraph.prebuilt`.
  §2.2 A checkpointer is mandatory for interrupt/resume.
  §2.3 Interrupts are deterministic: the node re-executes from the top on resume; `interrupt()` must be the **first statement**, no side effects before it.
  §2.6 Every node records usage into `usage_log` — `approval_gate` performs no LLM call, so it logs nothing (correct).
- **API contract (F6 consumes, do not drift):** `POST /api/runs {topic} → 201 {run_id, thread_id}`; `POST /api/runs/{run_id}/resume {action, plan?} → 202`. F5 builds the `RunService` these endpoints will call, but **adds no HTTP routes** (that is F6).
- **SSE (F6):** the `{type:"interrupt"; payload:{plan}}` event will be emitted from the interrupt payload F5's `RunService.start` surfaces — so `start` must return the plan payload to its caller.

---

### Context deltas

Two edits to the shared context are required **before** implementation:

1. **§4 repo layout — add one file:** `backend/app/services/run_service.py` (new `app/services/` package with `__init__.py`). `RunService` coordinates graph + checkpointer + `runs_repo` and is the object F6's API layer calls. Rationale: keeps `graph/` pure graph and `persistence/` pure storage; the orchestration seam gets its own home. (Alternative considered: `app/graph/run_service.py` — rejected to avoid mixing lifecycle orchestration into the graph package.)
2. **Ownership correction:** `app/persistence/runs_repo.py`'s current stub docstring says *"implemented in F6"* — F5 owns it (this feature's scope §3). Update the docstring accordingly. No §5 state-schema fields are added or renamed. No new API routes.

**No new environment variables.** The `runs` table reuses the existing `CHECKPOINT_BACKEND` / `DATABASE_URL` settings for backend selection (see Implementation notes).

---

### Scope

1. **`app/graph/nodes/approval.py::approval_gate(state)`** — the interrupt gate. `interrupt()` is the first and only pre-branch statement (deterministic re-execution, §2.3):
   ```python
   from langgraph.types import interrupt
   from app.graph.state import MAX_SECTIONS, ResearchState, SectionPlan

   def approval_gate(state: ResearchState) -> dict:
       decision = interrupt({"plan": [s.model_dump() for s in state["plan"]]})
       if decision["action"] == "edit":
           plan = [SectionPlan(**s) for s in decision["plan"]][:MAX_SECTIONS]
           return {"plan": plan, "plan_approved": True, "status": "researching"}
       return {"plan_approved": True, "status": "researching"}
   ```
   Resume payload shape: `{"action": "approve"}` or `{"action": "edit", "plan": [ {id,title,objective,suggested_queries}, ... ]}`. Edited plans are clamped to `MAX_SECTIONS`. No `usage_log` entry (no model call).

2. **Rewire `app/graph/builder.py`** — insert the gate between planner and fan-out; `fan_out` re-anchors onto `approval_gate`:
   ```python
   from app.graph.nodes.approval import approval_gate
   ...
   graph.add_node("approval_gate", approval_gate)
   graph.add_edge(START, "planner")
   graph.add_edge("planner", "approval_gate")
   graph.add_conditional_edges("approval_gate", fan_out, ["worker"])   # replaces the planner→fan_out edge
   # (worker → reviewer, reviewer conditional, writer → END unchanged)
   ```
   Update the module docstring's topology line to `planner → approval_gate(interrupt) → [fan_out] worker×N → reviewer → … → writer`.

3. **`app/persistence/runs_repo.py::RunsRepo`** — thin, hand-written run-metadata store (no SQLAlchemy, no Alembic — deliberate tradeoff, stated in README). Backend-selected like the checkpointer: stdlib `sqlite3` on a file `atlas_runs.sqlite` when `CHECKPOINT_BACKEND=="sqlite"`, `psycopg` over `DATABASE_URL` otherwise. `CREATE TABLE IF NOT EXISTS` bootstrap on construction (no migrations).
   Table `runs`: `run_id TEXT PRIMARY KEY`, `thread_id TEXT NOT NULL`, `topic TEXT NOT NULL`, `status TEXT NOT NULL`, `created_at TEXT NOT NULL` (ISO-8601 UTC), `cost_usd REAL NOT NULL DEFAULT 0`, `report_md TEXT NULL`.
   ```python
   class RunRow(BaseModel):
       run_id: str; thread_id: str; topic: str; status: str
       created_at: str; cost_usd: float; report_md: str | None

   class RunsRepo:
       def __init__(self, db_path: str | None = None) -> None: ...   # bootstraps table
       def create(self, run_id: str, thread_id: str, topic: str) -> RunRow: ...  # status="planning"
       def update(self, run_id: str, *, status: str,
                  cost_usd: float | None = None, report_md: str | None = None) -> None: ...
       def get(self, run_id: str) -> RunRow | None: ...
       def list(self) -> list[RunRow]: ...                            # newest first
   ```
   All SQL parameterized. `db_path` override exists so tests point at a `tmp_path` file. Use `?` placeholders for sqlite; keep a single `_execute` helper that swaps placeholder style for psycopg.

4. **`app/services/run_service.py::RunService`** — lifecycle orchestrator consumed by F6.
   ```python
   from collections.abc import Iterator
   from contextlib import AbstractContextManager

   class StartResult(BaseModel):
       run_id: str; thread_id: str; status: str
       interrupt_plan: list[dict] | None   # the {"plan":[...]} payload when paused, else None

   class RunService:
       def __init__(self, repo: RunsRepo,
                    checkpointer_cx=checkpointer_cx) -> None: ...     # cx injectable for tests

       async def start(self, topic: str) -> StartResult: ...
       async def resume(self, run_id: str, decision: dict) -> RunRow: ...
   ```
   - `start`: `run_id, thread_id = uuid4()` (distinct); `repo.create(...)` (row → `planning`); then run the graph to its first stop via `asyncio.to_thread(self._invoke, ...)` (keeps the event loop free while the sync graph/checkpointer run). Inside the thread: `with checkpointer_cx() as cp: g = build_graph(cp); g.invoke(_seed_state(topic), config)`; read the canonical stop state from `g.get_state(config)` — `status = snap.values["status"]`, `cost = sum(e.cost_usd for e in snap.values["usage_log"])`, interrupt payload from `snap.interrupts[0].value` if `snap.interrupts` else `None`. `repo.update(run_id, status=status, cost_usd=cost)`. Return `StartResult(..., interrupt_plan=payload["plan"] if payload else None)`.
   - `resume`: `row = repo.get(run_id)`; `config={"configurable":{"thread_id": row.thread_id}}`; in a thread, `with checkpointer_cx() as cp: g = build_graph(cp); g.invoke(Command(resume=decision), config)`; re-read `g.get_state(config)`; `repo.update(run_id, status=snap.values["status"], cost_usd=<sum>, report_md=snap.values.get("final_report_md") or None)`. Return the refreshed `RunRow`.
   - `_seed_state(topic)` mirrors `demo._seed_state` (all state keys initialised; `status="planning"`). A fresh `checkpointer_cx()` per call is intentional — it is what makes restart-durability real (no long-lived connection).

5. **`app/graph/demo.py` — add `--interactive`.** When `argv` contains `--interactive`: build the graph under `checkpointer_cx()`, `invoke` to the interrupt, print the plan from `get_state(config).interrupts[0].value["plan"]`, then read a keypress:
   - `y` → `graph.invoke(Command(resume={"action": "approve"}), config)`.
   - `e` → prompt `keep N sections:`, build edited plan = first `N` of the current plan, `graph.invoke(Command(resume={"action": "edit", "plan": edited}), config)`.
   Print the same final summary (plan outline, drafts count, report, `total_cost_usd`). Keep the existing non-interactive path working. Use a fixed `thread_id` when `--interactive` is passed **and** an explicit `--thread <id>` is given, so the "kill at pause, rerun same thread, resume" verify works; otherwise `uuid4()`.

6. **README** — add an `## F5` section: what the gate does, the resume payload shapes, the two deliberate tradeoffs (`CREATE TABLE IF NOT EXISTS` bootstrap instead of Alembic; `runs` metadata co-located in a sqlite file in dev), and the exact `--interactive` / restart Verify commands.

---

### Out of scope

- HTTP endpoints `POST /api/runs`, `POST /api/runs/{run_id}/resume`, `GET /api/runs*` — **F6** (F5 only builds `RunService` + `RunsRepo` they call).
- SSE translation of the `interrupt` event — **F6**.
- Frontend `PlanApprovalPanel` and approval UI — **F11**.
- Streaming writer tokens / `token` events — **F7**.
- Any change to worker, reviewer, writer, or routing logic beyond re-anchoring `fan_out` onto `approval_gate`.

---

### Implementation notes

- **Verified against installed packages:** `langgraph==1.2.9`, `langgraph-checkpoint-sqlite==3.1.0`, `langgraph-checkpoint-postgres==3.1.0`, `pydantic>=2`.
  - `interrupt` and `Command` are in **`langgraph.types`** (confirmed in `langgraph/types.py`: `def interrupt(value)`, `class Command(... resume: dict|Any|None = None)`). Do **not** import from `langgraph.prebuilt` (§2.1).
  - On interrupt, `graph.invoke(...)` returns the state values dict plus a `"__interrupt__"` key holding a `tuple[Interrupt, ...]`; each `Interrupt` has `.value` and `.id`. The **canonical, restart-safe** read is `graph.get_state(config)` → `StateSnapshot` with `.values` (state dict), `.next` (tuple of pending node names — non-empty while paused), and `.interrupts: tuple[Interrupt, ...]`. Prefer `get_state` over the invoke return value for status/cost/payload so `start` and `resume` read state the same way.
  - Resume is `graph.invoke(Command(resume=<decision-dict>), config)` with the **same** `config["configurable"]["thread_id"]`.
- **Determinism (§2.3):** `approval_gate` calls `interrupt()` unconditionally as its first statement — the whole node re-runs on resume, and the only work before the branch is building the payload from existing `state["plan"]` (idempotent). Never guard `interrupt()` behind a condition.
- **Restart durability:** because `start` and `resume` each open a *fresh* `checkpointer_cx()` and a *fresh* `build_graph()`, resuming after a process restart is structurally identical to resuming in-process — the SqliteSaver file is the only shared state. This is exactly what the restart test asserts.
- **`psycopg`** is already present transitively via `langgraph-checkpoint-postgres`; the sqlite path uses stdlib `sqlite3` (no new dependency). If mypy/ruff flags the psycopg import as unresolved, keep it lazily imported inside the postgres branch (mirrors `checkpointer.py`'s lazy `PostgresSaver` import).
- **Async seam:** graph invocation and both savers are synchronous; wrap them with `asyncio.to_thread(...)` in `RunService` so F6's async endpoints never block the event loop. Do not introduce `AsyncSqliteSaver` — the sync saver + thread offload is sufficient and matches the checkpointer factory.
- **sqlite3 timestamps:** store `created_at` as `datetime.now(timezone.utc).isoformat()`; list ordering `ORDER BY created_at DESC`.

---

### Test plan

Use `MemorySaver` for graph-level interrupt/resume behavior, a real `SqliteSaver` temp file for the durability proof, and a `tmp_path` sqlite file for `RunsRepo`/`RunService`. Reuse `tests/fakes.py` (`FakeModel`, `FakeReviewModel`, `ai`) and the `_FakeModel`/`_FakeStructuredModel` planner-fake pattern from `test_graph_invoke.py`. Monkeypatch `planner_mod.get_model`, `worker_mod.get_model`, `worker_mod.get_worker_tools`, `reviewer_mod.get_model` before `build_graph`.

- **`tests/test_approval_gate_unit.py`** — call `approval_gate` directly:
  - `{"action":"approve"}` → returns `{"plan_approved": True, "status": "researching"}` and no `plan` key (plan unchanged); no `usage_log` key.
  - `{"action":"edit","plan":[<2 sections>]}` → returns edited `plan` (len 2) + `status="researching"`.
  - `{"action":"edit","plan":[<7 sections>]}` → returned `plan` clamped to `MAX_SECTIONS` (6). *(covers the researching transition + clamp deterministically.)*
- **`tests/test_approval_interrupt.py`**:
  - **pauses at approval:** invoke seed with a 2-section planner fake; `graph.get_state(config)` has non-empty `.interrupts`, `.next` points at `approval_gate`, `values["status"]=="awaiting_approval"`, and `interrupts[0].value["plan"]` has the 2 planned sections (its `__interrupt__` payload contains the plan).
  - **resume approve completes:** `Command(resume={"action":"approve"})` → `values["status"]=="done"`, `final_report_md` non-empty, `len(drafts)==2` (plan unchanged, one draft per section; reviewer approves in one wave).
  - **edit changes fan-out:** planner fake yields 3 sections; resume `edit` with a 2-section plan → exactly **2** drafts produced (fan-out honored the edited plan, not the original).
- **`tests/test_approval_restart.py`** — durability proof:
  - `saver1 = SqliteSaver.from_conn_string(str(tmp_path/"cp.sqlite"))`; enter it, `build_graph(saver1)`, invoke to interrupt, **exit** the context (simulates process death).
  - `saver2 = SqliteSaver.from_conn_string(<same file>)`; enter, `build_graph(saver2)`, `invoke(Command(resume={"action":"approve"}), config)` with the same `thread_id` → `status=="done"`. *(Acceptance: resume survives restart.)*
- **`tests/test_runs_repo.py`**: `RunsRepo(db_path=tmp)`; `create` → `get` round-trips with `status=="planning"`; `update(status=..., cost_usd=..., report_md=...)` persists; `list()` newest-first; constructing a second `RunsRepo` on the same file does not error (bootstrap idempotent).
- **`tests/test_run_service.py`** (inject a `checkpointer_cx` that yields a shared `MemorySaver` so state persists across `start`/`resume`; `RunsRepo(db_path=tmp)`):
  - `await start(topic)` → `StartResult.status=="awaiting_approval"`, `interrupt_plan` non-None with planned sections, distinct `run_id`/`thread_id`; repo row status `awaiting_approval`.
  - `await resume(run_id, {"action":"approve"})` → row `status=="done"`, `report_md` non-None, `cost_usd > 0`.
  - **status transition assertion:** row status is `awaiting_approval` after `start` and `done` after `resume` (the `planning → awaiting_approval → researching → done` chain: `planning` at `create`, `researching` proven by `test_approval_gate_unit`, `done` at resume end).

---

### Verify

```bash
cd backend
# 1. All tests (interrupt, restart-durability, repo, service):
uv run pytest -q

# 2. Live interactive gate against a real OpenAI key (.env in backend/):
uv run python -m app.graph.demo "Compare vector database pricing for a seed-stage startup" --interactive --thread demo-f5
#    → prints the plan, waits for y/e. Press Ctrl-C AT THE PAUSE to kill the process.

# 3. Restart proof — rerun with the SAME thread id and resume:
uv run python -m app.graph.demo "Compare vector database pricing for a seed-stage startup" --interactive --thread demo-f5
#    → re-attaches to thread demo-f5, reprints the persisted plan, 'y' resumes to a finished report + total_cost_usd.
```

Expected: step 1 exits 0 with the F5 tests passing; step 3 resumes a run that was interrupted in a **separate, killed** process — proving checkpointer durability.

---

### Acceptance criteria

- [ ] `approval_gate` calls `interrupt()` as its first statement; graph pauses after planning with `status=="awaiting_approval"` and an `__interrupt__`/`get_state().interrupts` payload containing the plan (`test_approval_interrupt.py`).
- [ ] Resume with `{"action":"approve"}` completes the run to `status=="done"` with a non-empty report (`test_approval_interrupt.py`).
- [ ] Editing the plan at approval changes the fan-out: an edited 2-section plan yields exactly 2 worker drafts; edits over `MAX_SECTIONS` are clamped to 6 (`test_approval_interrupt.py`, `test_approval_gate_unit.py`).
- [ ] Resume survives process restart: a fresh graph object over the same SqliteSaver file resumes a previously-interrupted thread to `done` (`test_approval_restart.py`).
- [ ] `runs` row transitions `planning → awaiting_approval → done` across `RunService.start`/`resume`, with `cost_usd` populated (> 0) and `report_md` set on completion; the `researching` transition is asserted at the node level (`test_run_service.py`, `test_approval_gate_unit.py`).
- [ ] `RunsRepo` bootstraps its table idempotently and round-trips `create/get/update/list` (`test_runs_repo.py`).
- [ ] `uv run pytest -q` passes; `mypy` and `ruff` are clean; README has an `## F5` section; no new secrets/env vars introduced.
