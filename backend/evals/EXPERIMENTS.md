# F9 — Model routing cost experiment

**Question:** How much cheaper is role-based model routing than always using the strong
model, and does it cost us task success?

OpenAI is the sole provider (§3): the strong tier is `openai:gpt-4o`, the cheap tier
`openai:gpt-4o-mini`. We compare three routing configurations along two axes — **cost**
(answered now, no new spend) and **success/quality** (deferred to a live run).

## Configurations

| Config | planner | reviewer | writer | worker |
| --- | --- | --- | --- | --- |
| (a) all-gpt-4o | gpt-4o | gpt-4o | gpt-4o | gpt-4o |
| (b) routed (default) | gpt-4o | gpt-4o | gpt-4o | **gpt-4o-mini** |
| (c) all-gpt-4o-mini | gpt-4o-mini | gpt-4o-mini | gpt-4o-mini | gpt-4o-mini |

Rationale for the routed default: the fan-out **worker** is the highest-volume role (N
sections × up to `MAX_TOOL_CALLS_PER_WORKER` model turns each), so moving just the worker
to the cheap tier captures most of the cost while keeping the quality-sensitive planning,
reviewing, and final writing on the strong model.

## Cost result (derived, no new API spend)

**Method.** Cost is a pure function of `tokens × price`. An existing F8 benchmark run
(`evals/results/20260722-090349/`) was produced with the F2 stub router, i.e. **every role
ran on `gpt-4o-mini`** — so it *is* config (c), measured, with real per-node costs in
`results.jsonl`. The `gpt-4o` : `gpt-4o-mini` price ratio is **uniform across input and
output tokens** (2.50/0.15 = 10.00/0.60 = **16.667×**), so each node's measured cheap-tier
cost can be re-priced into the strong tier by a single multiply — no input/output token
split needed. `evals/project_costs.py` re-prices the measured baseline into configs (a) and
(b) exactly. Reproduce with:

```bash
cd backend
uv run python evals/project_costs.py --results-dir evals/results/20260722-090349
```

**Result** (n = 4 priced runs, seed 42):

| Config | Mean cost / run | Basis |
| --- | --- | --- |
| (a) all-gpt-4o | **$0.3995** | projected (×16.667 on every node) |
| (b) routed (default) | **$0.1250** | projected (worker stays cheap) |
| (c) all-gpt-4o-mini | **$0.0240** | **measured** (`results/20260722-090349`) |

- **Routed vs all-gpt-4o cost saving: `1 − 0.1250/0.3995` = 68.7%.**
- All-gpt-4o-mini vs all-gpt-4o: 94.0% (but see quality caveat below).

**Assumption.** The projection holds token *trajectories* fixed across tiers (same number
of revision loops, tool calls, and tokens per node). A stronger model may revise less (or
more), so the projected strong-tier costs are estimates, not measurements. The cheap-tier
row is fully measured.

## Success / quality (DEFERRED — requires a live run)

Re-pricing cannot tell us whether the cheaper worker *degrades output quality* — that is
exactly what differs between models and cannot be inferred from cost. The measured baseline
run scored 0% success (all four runs failed the groundedness grader), which also suggests
that F8 run needs revisiting, independent of routing.

Answering "does routing hold success within 3 points of all-gpt-4o?" requires running the
three configs live. This has **not** been done (no API credit budgeted). When credit is
available, run the protocol below and fill the quality table.

### Live protocol (to complete the quality comparison)

Controls: n = 20, seed = 42, all four categories, identical topics across configs
(seed-deterministic). Judge held constant at `EVAL_JUDGE_MODEL=openai:gpt-4o` (not part of
`MODEL_ROUTING`), so grading is identical across rows. Each config is a **separate process**
(the router caches models per role for the process lifetime).

```bash
cd backend   # needs live OPENAI_API_KEY + TAVILY_API_KEY
# (a) all-gpt-4o
MODEL_ROUTING='{"planner":"openai:gpt-4o","reviewer":"openai:gpt-4o","writer":"openai:gpt-4o","worker":"openai:gpt-4o"}' \
  uv run python evals/run_benchmark.py --n 20 --seed 42
# (b) routed — the built-in default; no override needed
uv run python evals/run_benchmark.py --n 20 --seed 42
# (c) all-gpt-4o-mini
MODEL_ROUTING='{"planner":"openai:gpt-4o-mini","reviewer":"openai:gpt-4o-mini","writer":"openai:gpt-4o-mini","worker":"openai:gpt-4o-mini"}' \
  uv run python evals/run_benchmark.py --n 20 --seed 42
```

| Config | Success rate | p50 latency (s) | p95 latency (s) | Source dir |
| --- | --- | --- | --- | --- |
| (a) all-gpt-4o | _tbd_ | _tbd_ | _tbd_ | `results/________` |
| (b) routed (default) | _tbd_ | _tbd_ | _tbd_ | `results/________` |
| (c) all-gpt-4o-mini | 0.0%¹ | 146.3 | 158.4 | `results/20260722-090349` |

¹ Measured, but n = 4 and the groundedness failures make this run unreliable as a quality
baseline — re-run at n = 20 alongside (a) and (b).

## Decision

**Cost (settled):** routing to the cheap worker cuts mean cost/run ~**69%** vs all-gpt-4o
while leaving every quality-sensitive role (planner, reviewer, writer) on the strong model.
On cost alone the routed config is the clear default, so `MODEL_ROUTING` ships with the
routed map (worker → `gpt-4o-mini`, rest → `gpt-4o`).

**Quality (open):** the "success within 3 points of all-gpt-4o" gate is **not yet verified**
— it needs the live protocol above. If a live run shows the routed config drops success by
more than 3 points, revisit the default (move the worker back to `gpt-4o`, or route only the
first-draft turn cheap). Until then the routed default is adopted on the cost result with the
quality check explicitly outstanding.

## Future work (out of scope for F9)

- Router-level retry / rate-limit / backoff handling (the F2 docstring anticipated it; no
  feature owns it yet).
- Per-topic or per-difficulty dynamic model selection (routing is currently static per role).
