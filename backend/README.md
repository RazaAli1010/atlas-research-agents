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

## F7 — report quality: citations, dedup & export

The writer produces an analyst-grade report with a fixed structure and verifiable
citations, and the report is downloadable as Markdown.

### Structure contract

Every report follows this skeleton exactly (a structure test parses the headings):

```
# {topic}
## Executive summary        (LLM-written, ≤150 words, no citation markers)
## 1. {section title}       (sections in plan order; global [n] markers)
## 2. ...
## Limitations              (always present; "None." when nothing to report)
## Sources                  (deduplicated, numbered; [n] markers resolve here)
```

- **Global citations.** Workers number sources locally; the writer remaps every `[n]`
  to a single deduplicated global source list (duplicate URLs collapse to one entry).
- **Zero dangling markers.** A marker that does not resolve to a source is stripped, and
  the removal is reported under *Limitations* (e.g. "N citation marker(s) … removed").
- **Executive summary** is written by the writer via `get_model("writer")` — this is the
  LLM call that now emits the SSE `token` deltas (previously dormant).
- **Snippet hygiene.** `Source.snippet` is structurally clamped to ≤300 chars by a
  Pydantic validator, so no long verbatim quotes are ever stored.

### Export

| Method & path | Behavior |
| --- | --- |
| `GET /api/runs/{run_id}/report.md` | `200` Markdown download (`Content-Disposition: attachment`); `404` unknown run; `409` if no report yet |

Serves the persisted `runs.report_md`, falling back to the live graph-state snapshot.

```bash
curl -s -D - localhost:8000/api/runs/$RID/report.md -o report.md   # attachment headers
```

**PDF/DOCX export is deliberately out of scope** — the Markdown download is the single
export format; rendering to other formats is left to the client.

## F8 — evaluation harness

Measures Atlas like production software: task success rate, per-grader scores,
trajectory stats, cost, and latency over a fixed 40-topic benchmark
(`evals/benchmark_topics.jsonl`, 10 each across `tech_comparison`, `market_overview`,
`how_it_works`, `pricing_quant`).

### Run

```bash
# needs OPENAI_API_KEY + TAVILY_API_KEY in backend/.env
uv run python evals/run_benchmark.py --n 10           # 10 topics
uv run python evals/run_benchmark.py --smoke          # 3 topics, cheap judge (fast/cheap)
uv run python evals/run_benchmark.py --category pricing_quant --n 5
```

Each run auto-approves its plan (programmatic `Command(resume={"action":"approve"})`),
runs graders, and writes `evals/results/{timestamp}/results.jsonl` + `summary.md`
(aggregate success rate, p50/p95 latency, mean cost, a **failure-taxonomy table** grouped
by first-failing grader, and a **per-category** breakdown). Concurrency is capped at 3.

### Graders & the fixed success rule (`evals/graders.py`)

| Grader | Kind | Checks |
| --- | --- | --- |
| `structure` | programmatic | report obeys the F7 heading contract |
| `citation` | programmatic | no dangling markers; ≥1 source per section; **no fabricated source URLs** (every cited web/rag URL appeared in an actual tool result — see below) |
| `coverage` | LLM judge | fraction of `must_cover` points addressed |
| `groundedness` | LLM judge | 5 sampled cited claims are supported by their source snippet |

**Success (fixed):** `structure` AND `citation` pass, `coverage ≥ 0.8`, `groundedness ≥ 0.8`.

### Anti-fabrication ground truth

The worker records a `ToolCallRecord` per tool invocation into `state["tool_calls"]`
(the append-reducer field added to §5). The `citation` grader compares every cited
source URL against this independent record — so a source URL that never came from a tool
result is flagged as fabricated (`tests/test_citation_grader_antifab.py`).

### Determinism

Topic selection and grader sampling are fully reproducible given `--seed` (default 42):
same flags → same topics, same sampled claims. The underlying LLM/tool outputs are **not**
deterministic, so grader *scores* may vary run to run — only the *inputs and sampling* are
reproducible.

### CI

The full test suite (including all offline graders) runs on every PR. The **smoke**
benchmark is a manually-triggered workflow (`.github/workflows/evals-smoke.yml`,
`workflow_dispatch`) — kept off per-PR CI because it makes real, billable model/tool calls.
Trigger it from the Actions tab; it runs `--smoke` and uploads the results directory.
