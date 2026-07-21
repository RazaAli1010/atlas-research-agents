# Atlas backend

FastAPI service wrapping the LangGraph research agent (planner → approval → parallel
workers → reviewer → writer).

## Run (local dev, sqlite checkpointer)

```bash
cd backend
uv sync
# secrets in backend/.env (see app/config.py): OPENAI_API_KEY, TAVILY_API_KEY
uv run uvicorn app.main:app --port 8000
```

Health check: `curl -s localhost:8000/api/health` → `{"status":"ok"}`.

Tests / lint / types:

```bash
uv run pytest -q
uv run ruff check app tests
uv run mypy app
```

## F6 — run lifecycle & SSE streaming

The HTTP surface (SHARED CONTEXT §7). `POST /api/runs` returns immediately; the graph
runs as a per-run background asyncio task that streams typed `AtlasEvent`s.

| Method & path | Behavior |
| --- | --- |
| `POST /api/runs` `{topic}` | `201 {run_id, thread_id}` — starts a run; graph runs in the background |
| `GET /api/runs` | `200 [{run_id, topic, status, created_at, cost_usd}]` (newest first) |
| `GET /api/runs/{run_id}` | `200` full state snapshot (`RunDetail`) |
| `POST /api/runs/{run_id}/resume` `{action, plan?}` | `202` — `approve` or `edit` the plan; `404` unknown, `409` if not `awaiting_approval`, `422` bad edit payload |
| `GET /api/runs/{run_id}/events` | SSE stream of `AtlasEvent`s |

### SSE stream (`AtlasEvent`)

One JSON object per event; the SSE `event:` field is the `type`. Variants (defined and
validated in `app/api/sse.py`): `status`, `node_started`, `node_finished`, `token`,
`interrupt`, `usage`, `review`, `done`, `error`.

Events are buffered per run in an in-memory registry, so a client connecting **mid-run
or after completion** first replays the full ordered history, then live-tails. The
stream ends on `done`/`error`; it stays open at `interrupt` (awaiting resume).

Stream translation uses LangGraph `astream(stream_mode=["tasks", "messages"])`: `tasks`
→ `node_started`/`node_finished` plus the node's `status`/`review`/`usage` writes;
`messages` → writer `token` deltas. `interrupt`/`done` are read authoritatively from the
post-stream `graph.get_state(...)` snapshot, not synthesized from the stream.

### End-to-end demo

```bash
RID=$(curl -s -XPOST localhost:8000/api/runs -H 'content-type: application/json' \
      -d '{"topic":"Compare vector database pricing for a seed-stage startup"}' | jq -r .run_id)
curl -N localhost:8000/api/runs/$RID/events &            # live typed stream
sleep 3
curl -s -XPOST localhost:8000/api/runs/$RID/resume -H 'content-type: application/json' \
     -d '{"action":"approve"}' -o /dev/null -w '%{http_code}\n'   # 202
curl -s localhost:8000/api/runs | jq                     # run listed, status:"done"
```

### Known limitations (deliberate for this project)

- **Single-worker, in-memory event registry.** The per-run event buffer and background
  task registry live in the process and are unbounded. Horizontal scaling would require
  an external broker (e.g. Redis pub/sub) and a task queue — out of scope here.
- **Writer `token` events are dormant.** The transport is wired (`messages` mode →
  `token`, filtered to the writer node), but the current writer is a deterministic
  mechanical merge with no LLM call, so it emits no tokens. Real `token` events
  materialize automatically once the writer becomes a streaming LLM (a later feature);
  the authoritative report always ships in the `done` event.
