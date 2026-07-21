## F6 — FastAPI run lifecycle & SSE streaming

**Goal:** Expose the full §7 HTTP surface on top of the existing `RunService`, running each graph execution as a background asyncio task and streaming its live progress to clients as typed `AtlasEvent` SSE, with per-run buffering so a late-joining client replays full history and then live-tails.

**Depends on:** F1 (app factory, config, health), F2 (graph builder, state, router, checkpointer factory), F3 (worker/writer), F4 (reviewer, routing), F5 (`RunService`, `RunsRepo`, approval interrupt).

---

### Context digest

Exact contracts this feature must consume — restated so no other file needs to be open.

**§7 endpoints to implement (in `app/api/routes_runs.py`):**

```
POST   /api/runs                 {topic}            → 201 {run_id, thread_id}
GET    /api/runs                                    → 200 [{run_id, topic, status, created_at, cost_usd}]
GET    /api/runs/{run_id}                           → 200 RunDetail (full state snapshot)
POST   /api/runs/{run_id}/resume {action, plan?}    → 202
GET    /api/runs/{run_id}/events                    → SSE stream (AtlasEvent envelope)
```

`GET /api/runs/{run_id}/report.md` and `GET /api/health` are **not** F6 (report.md is F7; health already exists in `app/main.py`).

**§7 SSE envelope — every event is one JSON object, the SSE `event:` field set to `type`:**

```ts
type AtlasEvent =
  | { type: "status"; status: RunStatus }
  | { type: "node_started"; node: string; section_id?: string }
  | { type: "node_finished"; node: string; section_id?: string; summary: string }
  | { type: "token"; node: string; delta: string }               // writer streaming
  | { type: "interrupt"; payload: { plan: SectionPlan[] } }
  | { type: "usage"; event: UsageEvent; total_cost_usd: number }
  | { type: "review"; review: Review }
  | { type: "done"; report_md: string }
  | { type: "error"; message: string };
```

`RunStatus` is the state `status` Literal: `"planning" | "awaiting_approval" | "researching" | "reviewing" | "writing" | "done" | "failed"`.

**State models (from `app/graph/state.py`) referenced by events:**

```python
class Source(BaseModel):     url: str; title: str; snippet: str; tool: Literal["web_search","rag","calculator"]
class SectionPlan(BaseModel):  id: str; title: str; objective: str; suggested_queries: list[str]
class SectionDraft(BaseModel): section_id: str; content_md: str; sources: list[Source]; revision: int
class Review(BaseModel):       section_id: str; verdict: Literal["approved","revise"]; score: float; feedback: str
class UsageEvent(BaseModel):   node: str; model: str; input_tokens: int; output_tokens: int; cost_usd: float
```

**`RunService` (from `app/services/run_service.py`) — existing surface F6 builds beside:**
- `async start(topic) -> StartResult(run_id, thread_id, status, interrupt_plan)` — blocking `graph.invoke` in a thread, runs to the approval pause. **F6 adds a streaming path; the existing `start`/`resume` stay for non-streaming callers/tests.**
- `async resume(run_id, decision) -> RunRow`.
- Private helpers reused as-is: `_seed_state(topic) -> ResearchState`, `_total_cost(values) -> float`, and the injected `checkpointer_cx: Callable[[], AbstractContextManager[BaseCheckpointSaver]]` (defaults to `app.persistence.checkpointer.checkpointer_cx`).

**`RunsRepo` (from `app/persistence/runs_repo.py`):**
- `create(run_id, thread_id, topic) -> RunRow` (status `"planning"`), `update(run_id, *, status, cost_usd=None, report_md=None)`, `get(run_id) -> RunRow | None`, `list() -> list[RunRow]` (newest first).
- `RunRow(run_id, thread_id, topic, status, created_at, cost_usd, report_md)`.

**Graph resume/interrupt contract (from `app/graph/nodes/approval.py`, `run_service.py`):**
- `approval_gate` interrupts with `{"plan": [s.model_dump() for s in plan]}`.
- Resume decision dict: `{"action": "approve"}` **or** `{"action": "edit", "plan": [ {id,title,objective,suggested_queries}, ... ]}`; edited plan clamped to `MAX_SECTIONS` **inside** the node.
- After a run pauses, the pending plan is read authoritatively via `graph.get_state(config).interrupts[0].value["plan"]` (proven in `run_service._invoke_start`).

**Constants (`app/graph/state.py`):** `MAX_SECTIONS = 6`.

**Principles that bind F6:** §2.2 checkpointer selected by config (never hardcoded — always via `checkpointer_cx`); §2.4 typed state; the SSE envelope is a fixed contract — do not drift field names.

---

### Context deltas

Each item below is a required edit to shared context / project files **before or with** implementation.

1. **New dev dependency `pytest-asyncio`** (`backend/pyproject.toml` `[dependency-groups].dev`). SSE streaming tests need an async test loop with `httpx.AsyncClient(ASGITransport)` and in-process background tasks; the existing `asyncio.run` pattern cannot drive a long-lived stream + concurrent background task cleanly. Add `[tool.pytest.ini_options] asyncio_mode = "auto"`. No runtime dep, no env var.

2. **Writer `token` events are wired but dormant in F6 (documented limitation).** The F3 writer (`app/graph/nodes/writer.py`) is a deterministic mechanical merge with **no LLM call**, and its own docstring states "narrative synthesis is a later feature." F6 therefore builds the `messages`-mode → `token` translation **generically** (filtered to `langgraph_node == "writer"`) so real tokens flow automatically the day the writer becomes a streaming LLM — but with today's writer, zero `token` events are emitted, and the authoritative report ships in the `done` event. **The LLM writer conversion is its own future feature (see Out of scope); F6 does not modify `writer.py`.** This is a conscious deviation from the raw F6 brief's item 4 ("ensure the final synthesis call streams"): we build the transport, not a throwaway string-chunking hack. Record this in §5/README as: writer streams tokens only once it is LLM-backed.

3. **No new state fields, no new routes, no new env vars.** All event/response shapes below are derived from existing §5 models and the §7 envelope.

---

### Scope

#### 1. Event models + translation — `app/api/sse.py`

Pydantic mirror of the §7 `AtlasEvent` union (acceptance criterion) + pure translators from LangGraph stream chunks to events. **Translation is pure and side-effect-free so it is unit-testable with synthetic chunks.**

```python
# app/api/sse.py
from typing import Annotated, Literal, Union
from pydantic import BaseModel, Field, TypeAdapter
from app.graph.state import Review, SectionPlan, UsageEvent, ResearchState

RunStatus = Literal["planning","awaiting_approval","researching","reviewing","writing","done","failed"]

class StatusEvent(BaseModel):        type: Literal["status"] = "status"; status: RunStatus
class NodeStartedEvent(BaseModel):   type: Literal["node_started"] = "node_started"; node: str; section_id: str | None = None
class NodeFinishedEvent(BaseModel):  type: Literal["node_finished"] = "node_finished"; node: str; section_id: str | None = None; summary: str
class TokenEvent(BaseModel):         type: Literal["token"] = "token"; node: str; delta: str
class InterruptPayload(BaseModel):   plan: list[SectionPlan]
class InterruptEvent(BaseModel):     type: Literal["interrupt"] = "interrupt"; payload: InterruptPayload
class UsageEventMsg(BaseModel):      type: Literal["usage"] = "usage"; event: UsageEvent; total_cost_usd: float
class ReviewEvent(BaseModel):        type: Literal["review"] = "review"; review: Review
class DoneEvent(BaseModel):          type: Literal["done"] = "done"; report_md: str
class ErrorEvent(BaseModel):         type: Literal["error"] = "error"; message: str

AtlasEvent = Annotated[
    Union[StatusEvent, NodeStartedEvent, NodeFinishedEvent, TokenEvent,
          InterruptEvent, UsageEventMsg, ReviewEvent, DoneEvent, ErrorEvent],
    Field(discriminator="type"),
]
AtlasEventAdapter: TypeAdapter[AtlasEvent] = TypeAdapter(AtlasEvent)

def to_sse(ev: BaseModel) -> dict[str, str]:
    """Serialize one event to an sse-starlette payload: event: <type>, data: <json>."""
    return {"event": ev.type, "data": ev.model_dump_json()}   # type: ignore[attr-defined]
```

Cost accumulator + chunk translators. LangGraph 1.x `graph.astream(..., stream_mode=["tasks","messages"])` yields `(mode, data)` tuples (verified — see Implementation notes). We use **`"tasks"`** (node start/finish + the node's channel writes) and **`"messages"`** (LLM token deltas):

```python
class CostAccumulator:
    def __init__(self, seed: float = 0.0) -> None: self.total = seed
    def add(self, c: float) -> float: self.total += c; return self.total

def _is_task_result(data: dict) -> bool:
    # TaskResultPayload has "result"/"error"/"interrupts"; TaskPayload has "input"/"triggers".
    return "result" in data or "error" in data

def _section_id_from_task(node: str, data: dict) -> str | None:
    if node != "worker": return None
    # start: Send input {"section": SectionPlan|dict, ...}; finish: result {"drafts": [SectionDraft...]}
    ...  # best-effort: input["section"].id / dict["id"], else first produced draft's section_id; else None

def _summary(node: str, result: dict) -> str:
    # planner→"Planned N sections", worker→f"Drafted section {sid}", reviewer→"Reviewed N section(s)",
    # approval_gate→"Awaiting plan approval", writer→"Synthesized final report". Derive N from result.

def chunk_to_events(mode: str, data, cost: CostAccumulator) -> list[BaseModel]:
    """Pure: map one (mode, data) chunk to zero-or-more AtlasEvents. No I/O."""
    events: list[BaseModel] = []
    if mode == "tasks":
        node = data["name"]
        if not _is_task_result(data):
            events.append(NodeStartedEvent(node=node, section_id=_section_id_from_task(node, data)))
        else:
            result = data.get("result") or {}
            # status change → StatusEvent
            if isinstance(result, dict) and result.get("status"):
                events.append(StatusEvent(status=result["status"]))
            # reviewer/worker/planner channel writes → review + usage events
            for rv in (result.get("reviews") or []):
                events.append(ReviewEvent(review=rv))
            for ue in (result.get("usage_log") or []):
                events.append(UsageEventMsg(event=ue, total_cost_usd=cost.add(ue.cost_usd)))
            events.append(NodeFinishedEvent(node=node, section_id=_section_id_from_task(node, data),
                                            summary=_summary(node, result if isinstance(result, dict) else {})))
    elif mode == "messages":
        msg, meta = data                       # (AIMessageChunk, metadata)
        if meta.get("langgraph_node") == "writer" and isinstance(msg.content, str) and msg.content:
            events.append(TokenEvent(node="writer", delta=msg.content))
    return events

def terminal_events(snap) -> list[BaseModel]:
    """After astream drains: emit interrupt (paused) or done (finished) from the state snapshot."""
    if snap.interrupts:
        plan = [SectionPlan(**s) for s in snap.interrupts[0].value["plan"]]
        return [InterruptEvent(payload=InterruptPayload(plan=plan))]
    report = snap.values.get("final_report_md") or ""
    return [DoneEvent(report_md=report)] if report else []
```

> **Ordering note:** in a `tasks` result we emit `status` → `review*` → `usage*` → `node_finished` so the timeline reads coherently; `interrupt`/`done` come only from `terminal_events` after the stream drains (never mid-stream), which keeps the F5-proven `get_state` the single authority for the pending plan.

#### 2. Streaming lifecycle methods — `app/services/run_service.py`

Add async-generator-free **emit-callback** streaming methods beside the existing `start`/`resume`. `emit` is an injected `async` callback the API supplies (writes to the run's buffer/subscribers) — this keeps `RunService` transport-agnostic and unit-testable with a list-appending fake.

```python
Emit = Callable[[BaseModel], Awaitable[None]]

async def stream_run(self, run_id: str, thread_id: str,
                     kickoff: ResearchState | Command, emit: Emit) -> None:
    """Drive one graph phase (start=seed state, resume=Command) to its next stop,
    emitting AtlasEvents live, then a terminal interrupt/done. Updates the runs row."""
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    row = self._repo.get(run_id)
    cost = CostAccumulator(seed=row.cost_usd if row else 0.0)
    try:
        with self._cx() as cp:
            graph = build_graph(cp)
            async for mode, data in graph.astream(kickoff, config=config,
                                                   stream_mode=["tasks", "messages"]):
                for ev in chunk_to_events(mode, data, cost):
                    await emit(ev)
            snap = graph.get_state(config)
        values = snap.values
        for ev in terminal_events(snap):
            await emit(ev)
        self._repo.update(run_id, status=values["status"], cost_usd=_total_cost(values),
                          report_md=values.get("final_report_md") or None)
    except Exception as exc:                      # graph failure → error event + failed row
        await emit(ErrorEvent(message=str(exc)))
        self._repo.update(run_id, status="failed")
        raise
```

- `stream_start`: `self._repo.create(...)` happens in the **route** (so the 201 body has ids immediately); the route then spawns `stream_run(run_id, thread_id, _seed_state(topic), emit)`.
- `stream_resume`: route validates + spawns `stream_run(run_id, thread_id, Command(resume=decision), emit)`.
- **Async + sync checkpointer:** `graph.astream` runs the sync graph nodes and the sync `SqliteSaver` in the loop's executor; `SqliteSaver.from_conn_string` opens the connection with `check_same_thread=False` + an internal lock (verified), so cross-thread use during `astream` is safe. The `with self._cx()` block stays open for the whole stream.

Add a **snapshot** method for `GET /api/runs/{run_id}`:

```python
async def get_detail(self, run_id: str) -> "RunDetail | None":
    row = self._repo.get(run_id)
    if row is None: return None
    def _snap() -> dict:
        with self._cx() as cp:
            return build_graph(cp).get_state({"configurable": {"thread_id": row.thread_id}}).values
    values = await asyncio.to_thread(_snap)
    return RunDetail.from_row_and_state(row, values)
```

#### 3. In-memory run registry + fan-out buffer — `app/api/routes_runs.py`

Per-run record holding the append-only event history (replay) and live subscriber queues. **Honest limitation:** in-process, unbounded, single-worker — documented in README; production would use a broker/queue (Redis pub/sub, etc.).

```python
@dataclass
class RunStream:
    buffer: list[dict[str, str]] = field(default_factory=list)   # serialized to_sse payloads
    subscribers: set[asyncio.Queue] = field(default_factory=set)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    finished: bool = False

    async def emit(self, ev: BaseModel) -> None:
        payload = to_sse(ev)
        async with self.lock:                       # atomic: append + fan-out (no lost/dup on subscribe)
            self.buffer.append(payload)
            if ev.type in ("done", "error"):
                self.finished = True
            for q in self.subscribers:
                q.put_nowait(payload)

    async def subscribe(self) -> tuple[list[dict], asyncio.Queue]:
        async with self.lock:                       # snapshot history + register atomically
            q: asyncio.Queue = asyncio.Queue()
            self.subscribers.add(q)
            return list(self.buffer), q

class RunRegistry:                                  # lives on app.state
    def __init__(self) -> None: self._runs: dict[str, RunStream] = {}
    def create(self, run_id: str) -> RunStream: ...
    def get(self, run_id: str) -> RunStream | None: ...
```

App wiring (`app/main.py::create_app`): construct once and stash on `app.state`:
```python
app.state.registry = RunRegistry()
app.state.run_service = RunService(RunsRepo())
```
Routes read `request.app.state.run_service` / `.registry` (a `get_run_service`/`get_registry` FastAPI dependency reading `request.app.state` is fine).

#### 4. Endpoints — `app/api/routes_runs.py` (`APIRouter`, included in `create_app`)

```python
class CreateRunRequest(BaseModel):  topic: str = Field(min_length=1)
class CreateRunResponse(BaseModel): run_id: str; thread_id: str
class RunSummary(BaseModel):        run_id: str; topic: str; status: str; created_at: str; cost_usd: float
class ResumeRequest(BaseModel):     action: Literal["approve","edit"]; plan: list[SectionPlan] | None = None
class RunDetail(BaseModel):         # full state snapshot
    run_id: str; thread_id: str; topic: str; status: str; created_at: str; cost_usd: float
    plan: list[SectionPlan]; plan_approved: bool; drafts: list[SectionDraft]; reviews: list[Review]
    revision_counts: dict[str, int]; final_report_md: str; usage_log: list[UsageEvent]
```

- **`POST /api/runs` → 201 `CreateRunResponse`.** `run_id, thread_id = uuid4()×2`; `run_service._repo.create(run_id, thread_id, topic)`; `stream = registry.create(run_id)`; spawn background task `asyncio.create_task(run_service.stream_run(run_id, thread_id, _seed_state(topic), stream.emit))` (keep a reference in a task registry dict keyed by `run_id` so it isn't GC'd; discard in a done-callback). Return immediately.
- **`GET /api/runs` → 200 `list[RunSummary]`** from `repo.list()` (drop `thread_id`/`report_md`).
- **`GET /api/runs/{run_id}` → 200 `RunDetail`** via `run_service.get_detail`; **404** if unknown.
- **`POST /api/runs/{run_id}/resume` → 202.** Validate `ResumeRequest`; `row = repo.get(run_id)` → **404** if unknown; **409** if `row.status != "awaiting_approval"`; if `action=="edit"` require non-empty `plan` (else **422**) and clamp to `MAX_SECTIONS`. Build `decision = {"action":"approve"}` or `{"action":"edit","plan":[p.model_dump() for p in plan]}`. Reuse the **same** `registry.get(run_id)` stream (resume events append to the existing buffer). Spawn `stream_run(run_id, row.thread_id, Command(resume=decision), stream.emit)`. Return `Response(status_code=202)`.
- **`GET /api/runs/{run_id}/events` → SSE** via `EventSourceResponse` (sse-starlette). **404** if `registry.get(run_id)` is `None`. Generator: `history, q = await stream.subscribe()`; yield every buffered payload (replay); then loop `payload = await q.get(); yield payload` until a payload whose event is `done`/`error` is seen **or** (`stream.finished` and queue drained). On client disconnect, unsubscribe in a `finally`. Each yielded value is the `to_sse` dict `{"event","data"}`.

`create_app` includes the router: `app.include_router(runs_router)`.

---

### Out of scope

- **LLM-backed streaming writer** (real writer `token` events) — its own future graph feature (the F3 writer docstring's "later feature"). F6 only wires the transport; it does not touch `writer.py`. Sequence it before/with F9's model router work.
- **`GET /api/runs/{run_id}/report.md`** — F7.
- **Persistent/brokered event bus, multi-worker fan-out, event backpressure/eviction** — production concern; F6 is single-process in-memory (documented).
- **Frontend `EventSource` consumption, `types.ts`** — F10.
- **Auth / rate limiting** — not in the project scope yet.

---

### Implementation notes

- **Verified versions (installed):** `langgraph 1.2.9`, `langgraph-checkpoint 4.1.1`, `langchain 1.3.14`, `langchain-core 1.5.0`, `langchain-openai 1.3.5`, `fastapi 0.139.2`, `sse-starlette 3.4.6`, `httpx 0.28.1`, `pydantic 2.x`.
- **`astream` multi-mode shape (verified in `langgraph/pregel/main.py`):** with `stream_mode` a **list**, each item is a `(mode, data)` tuple (a 3-tuple `(namespace, mode, data)` only when `subgraphs=True`, which we do **not** use).
- **`"tasks"` stream mode (verified in `langgraph/types.py`):** emits a `TaskPayload` on node start (`{id, name, input, triggers, metadata}`) and a `TaskResultPayload` on finish (`{id, name, error, interrupts, result}`) where `result` is the node's channel writes (the dict the node returned — e.g. `{"reviews":[...], "usage_log":[...], "status":...}`). Discriminate start vs finish by presence of `"result"`/`"error"`. Valid `StreamMode` values: `values, updates, checkpoints, tasks, debug, messages, custom`.
- **Why `tasks` not `updates` for start/finish:** `updates` mode emits only **post-node** deltas — it cannot signal `node_started` (there is no "node begins" record in it). The raw F6 brief said "updates → node_started/node_finished"; that is not achievable (a real "running now" signal is needed by the frontend timeline), so this spec uses `tasks`, which carries both a start and a finish payload. `updates` is not used.
- **`"messages"` mode:** yields `(message_chunk, metadata)`; filter `metadata["langgraph_node"] == "writer"`. With the deterministic F3 writer this yields nothing (no LLM inside the node) — dormant by design (Context delta 2).
- **Interrupt/done are authoritative from `get_state`, not the stream.** After `astream` drains, `graph.get_state(config).interrupts` (the F5-proven path, `run_service._invoke_start`) gives the pending plan; `values["final_report_md"]` gives the report. Do **not** synthesize `interrupt`/`done` from `tasks` payloads. Never import the private `INTERRUPT` constant (deprecated since LangGraph v1.0 → removed in v2.0); use `snap.interrupts`.
- **Sync checkpointer under async is safe:** `SqliteSaver.from_conn_string` opens with `check_same_thread=False` and guards with an internal lock (verified in `langgraph/checkpoint/sqlite/__init__.py`), so `astream` running nodes/saver in executor threads does not trip sqlite's thread affinity. Keep `with self._cx()` open for the whole stream.
- **Determinism / idempotency (§2.3):** the approval gate re-executes from the top on resume; the streaming path changes nothing here — `Command(resume=decision)` is fed exactly as F5's `resume` does. No side effects are added before the interrupt.
- **Background-task hygiene:** hold each `asyncio.Task` in a dict keyed by `run_id` until its done-callback removes it (prevents premature GC per asyncio docs). Run records persist in the registry for the process lifetime so post-completion late-join replay works (unbounded — documented limitation).
- **Subscribe/emit race:** take the record lock around *both* buffer-append+fan-out (`emit`) and history-snapshot+register (`subscribe`), so a client subscribing mid-emit sees each event exactly once (either in the replay snapshot or the live queue, never both/neither).
- **Cost accumulator** is seeded from the run row's current `cost_usd` at the start of each phase so `total_cost_usd` stays monotonic across start→resume.
- **CORS** already configured in `create_app` (F1) — SSE works through it; no change.

---

### Test plan

New tests under `backend/tests/` (mock all models via the F5 `_patch` pattern — `monkeypatch.setattr` on `planner_mod`/`worker_mod`/`reviewer_mod` `get_model`; `worker_mod.get_worker_tools → []`). Use `pytest-asyncio` (`asyncio_mode="auto"`) + `httpx.AsyncClient(transport=ASGITransport(app=create_app()))`.

1. **`test_sse_event_models.py` — envelope mirror + serializer (acceptance).**
   - Construct one of each `AtlasEvent` variant; assert `AtlasEventAdapter.validate_python(ev.model_dump())` round-trips and the discriminator resolves to the right class.
   - `to_sse(ev)` returns `{"event": ev.type, "data": <json>}` and `json.loads(data)["type"] == ev.type`.

2. **`test_sse_translation.py` — pure `chunk_to_events` (no server).**
   - `("tasks", {"name":"planner","input":...,"triggers":[]})` → `[NodeStartedEvent(node="planner")]`.
   - `("tasks", {"name":"planner","result":{"status":"awaiting_approval","usage_log":[UsageEvent(...)]},"interrupts":[]})` → `StatusEvent` + `UsageEventMsg(total_cost_usd=…)` + `NodeFinishedEvent`, in that order; accumulator advances.
   - `("tasks", {"name":"reviewer","result":{"reviews":[Review(...)],"usage_log":[UsageEvent(...)],"status":"reviewing"}, "interrupts":[]})` → contains one `ReviewEvent` and one `UsageEventMsg`.
   - `("messages", (AIMessageChunk(content="he"), {"langgraph_node":"writer"}))` → `[TokenEvent(node="writer", delta="he")]`; same chunk with `langgraph_node="reviewer"` → `[]`. **Proves the writer-token plumbing works even though the real writer is silent.**
   - `terminal_events`: a snapshot with `interrupts` → `InterruptEvent(payload.plan==…)`; a snapshot with `final_report_md` set and no interrupts → `DoneEvent`.

3. **`test_api_run_lifecycle.py` — end-to-end over ASGI (acceptance: endpoints + ordering).**
   - `POST /api/runs {topic}` → 201 with `run_id`, `thread_id`.
   - Open `GET /api/runs/{run_id}/events`; collect events until `interrupt`. Assert the ordered prefix: `status(planning)` → `node_started(planner)` → … → `node_finished(planner)` → `node_started(approval_gate)` → `node_finished(approval_gate)` → `interrupt` (payload plan length matches the mocked planner).
   - `POST /api/runs/{run_id}/resume {"action":"approve"}` → 202; continue reading the **same** stream until `done`; assert `done.report_md` is non-empty and that `node_started(worker)`, `review`, `node_finished(writer)` appeared between interrupt and done.
   - `GET /api/runs/{run_id}` → 200 `RunDetail` with `status=="done"`, non-empty `final_report_md`, `usage_log` non-empty.
   - `GET /api/runs` → 200 list containing the run with `status=="done"`, `cost_usd>0`.

4. **`test_api_resume_guards.py`**
   - Double-resume: after a run reaches `done`, a second `POST …/resume` → **409**. A resume on a still-`planning`/unknown run → **409**/**404** respectively.
   - `action:"edit"` with `plan:null` → **422**; with a >`MAX_SECTIONS` plan → 202 and downstream fan-out uses the clamped plan (assert `RunDetail.plan` length ≤ 6).

5. **`test_api_replay.py` — late-join (acceptance: full-history replay).**
   - Create + resume to completion **without** an events subscriber; then open `GET …/events` and assert the replayed stream contains the full ordered history and **ends in `done`** (with the report), then the generator closes.

---

### Verify

```bash
# from backend/, dev env (sqlite checkpointer)
uv run uvicorn app.main:app --port 8000 &
RID=$(curl -s -XPOST localhost:8000/api/runs -H 'content-type: application/json' \
      -d '{"topic":"Compare vector database pricing for a seed-stage startup"}' | jq -r .run_id)
curl -N localhost:8000/api/runs/$RID/events &        # live typed stream: status, node_started/finished, usage, interrupt
sleep 3
curl -s -XPOST localhost:8000/api/runs/$RID/resume -H 'content-type: application/json' -d '{"action":"approve"}' -o /dev/null -w '%{http_code}\n'   # 202
# the -N stream continues to review/usage/... and terminates with a `done` event carrying report_md
```

Expected: the `-N` stream shows `event: status`, `event: node_started`, `event: usage`, `event: interrupt`; after resume, `event: review`, `event: node_finished`, and a final `event: done` whose `data.report_md` is the full report. `pytest` (all F6 tests) and `curl -s localhost:8000/api/runs | jq` (the run listed, `status:"done"`) both succeed.

---

### Acceptance criteria

- [ ] All §7 endpoints except `report.md` (F7) implemented at exactly those paths with the specified payloads/status codes (`POST /api/runs`→201; `resume`→202; `GET` variants→200; SSE stream).
- [ ] `POST /api/runs` returns before the graph runs; execution proceeds in a background asyncio task tracked in a per-`run_id` registry.
- [ ] SSE events validate against the `AtlasEvent` Pydantic union and serialize with `event:` = `type` (test 1).
- [ ] Live stream ordering holds: `status` → `node_started(planner)` → … → `interrupt`, then after resume → `done` with a non-empty `report_md` (test 3).
- [ ] `POST …/resume` rejects with **409** when the run is not `awaiting_approval` (double-resume), and validates the edit payload against `SectionPlan` / clamps to `MAX_SECTIONS` (test 4).
- [ ] Late-join replay: subscribing **after** completion yields the full ordered history ending in `done` (test 5).
- [ ] Writer-token transport is exercised by a translation test (`messages`/`writer` chunk → `TokenEvent`), even though the deterministic writer emits none at runtime (test 2); README notes tokens materialize once the writer is LLM-backed.
- [ ] `mypy` (relaxed-strict) + `ruff` clean; `README.md` F6 section documents the endpoints, the single-worker in-memory streaming limitation, and the dormant writer-token behavior; no new secrets; `pyproject.toml` adds `pytest-asyncio` (dev).
