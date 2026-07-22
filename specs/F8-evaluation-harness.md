## F8 — Evaluation harness

**Goal:** Measure Atlas like production software — task success rate, per-grader scores, trajectory stats (revision loops, tool calls, cost-per-node), and latency — reproducibly, from a fixed benchmark topic set, emitting a machine-readable `results.jsonl` and a human-readable markdown summary.

**Depends on:** F2 (state schema, `build_graph`), F3 (worker + tools), F4 (reviewer/routing), F5 (`RunService`, `RunsRepo`, checkpointer), F7 (writer / report structure contract). Precedes F9 (real model router) — F8 must not depend on per-role routing.

---

### Context digest

Exact contracts this feature consumes (do not re-derive — use these names):

**State (`app/graph/state.py`, §5 — single source of truth):**
- `Source(url: str, title: str, snippet: str, tool: Literal["web_search","rag","calculator"])` — `snippet` is clamped to `MAX_SNIPPET_CHARS = 300`.
- `SectionPlan(id, title, objective, suggested_queries)`, `SectionDraft(section_id, content_md, sources: list[Source], revision)`, `Review(section_id, verdict: Literal["approved","revise"], score, feedback)`, `UsageEvent(node, model, input_tokens, output_tokens, cost_usd)`.
- `ResearchState` (TypedDict) fields used here: `topic`, `plan: list[SectionPlan]`, `drafts: Annotated[list[SectionDraft], operator.add]`, `reviews: Annotated[list[Review], operator.add]`, `revision_counts: dict[str,int]` (section_id → revisions produced, == highest draft revision), `usage_log: Annotated[list[UsageEvent], operator.add]`, `final_report_md: str`, `status`.
- Constants: `MAX_SECTIONS = 6`, `MAX_REVISIONS_PER_SECTION = 2`, `MAX_TOOL_CALLS_PER_WORKER = 8`, `RUN_COST_CEILING_USD = 1.50`.

**Report structure contract (F7, `app/graph/nodes/writer.py`):** headings in this exact order, each of the fixed three present exactly once:
```
# {topic}
## Executive summary
## 1. {title}        # one per section, numbered from 1 in plan order
## 2. {title}
…
## Limitations       # "None." when nothing to report
## Sources           # numbered "n. [title](url)" / "n. {expr} = {v} _(calculator)_"
```
The writer already guarantees every `[n]` marker in the report resolves to `1..len(sources)` (strips unresolved markers) and dedups sources by URL. Citation markers are 1-based; `[n]` in a `SectionDraft.content_md` indexes that draft's own `sources[n-1]` (worker-local numbering, F3).

**Worker tool loop (F3, `app/graph/nodes/worker.py`):** hand-written ReAct loop, `calls` counter bounded by `MAX_TOOL_CALLS_PER_WORKER`. `_collect(tool_name, args, result, sources, seen)` folds each tool result into `draft.sources` (dedup by URL, or `calc:{expr}` for calculator). `TOOL_NAME_TO_SOURCE_TOOL` maps a tool `.name` → the `Source.tool` literal. **Source URLs are built directly from tool output** — there is no independent record of what tools returned (this is why the anti-fabrication grader needs a Context delta, below).

**Router (`app/llm/router.py`, F2 stub):** `get_model(role)` returns one model (`settings.DEFAULT_MODEL = "openai:gpt-4o-mini"`) for all roles until F9; `track_usage(node, ai)` → `UsageEvent`. `MODEL_PRICES` keys: `gpt-4o-mini (0.15/0.60)`, `gpt-4o (2.50/10.00)` per 1M tokens. Structured output pattern (§2.7): `get_model(role).with_structured_output(Schema, include_raw=True)` returns `{"parsed": Schema, "raw": AIMessage}` (see `reviewer.py`).

**Run driving (F5, `app/graph/demo.py` / `RunService`):** graph pauses at the `approval_gate` interrupt after `planner`; resume with `Command(resume={"action":"approve"})`. Pattern: `build_graph(cp)` under `checkpointer_cx()`, `invoke(seed_state, config={"configurable":{"thread_id": tid}})`, read `graph.get_state(config)`, then `invoke(Command(resume={"action":"approve"}), config)`. Seed state shape is in `demo._seed_state`.

**Config (`app/config.py`):** `pydantic-settings` `Settings`; `LANGSMITH_TRACING: bool`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT="atlas"`. LangSmith env is exported from settings by `demo._enable_langsmith()`.

**Repo layout (fixed):** harness lives in `backend/evals/` (`benchmark_topics.jsonl`, `run_benchmark.py`, `graders.py`, `report_template.md`); tests in `backend/tests/`; CI in `.github/workflows/`.

**Principles that bind this feature:** §2.4 typed state (Pydantic v2 / TypedDict) — no new state field without updating §5 first; §2.6 cost tracking; §2.7 structured outputs (no regex-parsing JSON from prose); §2.8 12-factor config; §2.9 LangSmith observability; §2.11 verify installed library APIs before use.

---

### Context deltas

Three changes to the shared context, each required **before** implementation and each a small, contained edit:

**Delta 1 — §5 state schema: add a tool-call trace field (anti-fabrication ground truth + trajectory stats).**
The anti-fabrication grader must verify source URLs against an *independent* record of what tools actually returned, and §2 (spec point 4) requires tool-call counts "from state, not logs." The current graph retains neither. Add one field + one model to `state.py` and §5:
```python
class ToolCallRecord(BaseModel):
    section_id: str
    tool: Literal["web_search", "rag", "calculator"]
    urls: list[str]            # URLs this single tool call returned; [] for calculator
    contents: dict[str, str] = {}  # url -> full result text read (groundedness evidence); {} for calculator

class ResearchState(TypedDict):
    ...
    tool_calls: Annotated[list[ToolCallRecord], operator.add]   # append reducer (parallel workers)
```
This single field serves both needs: anti-fabrication ground-truth URL set = `{u for r in tool_calls for u in r.urls}`; tool-calls-per-section = count of `tool_calls` grouped by `section_id`. Chosen over a new `RunsRepo` column (the feature text's "add to `RunService`") because the harness drives the compiled graph directly and the checkpointer — which `RunService` owns — already persists graph state per thread, so a state field is durably persisted with **no** `runs`-table schema change and works identically for API-driven and harness-driven runs. `RunService` therefore needs no change; `RunsRepo` needs no change.

**Delta 2 — config: two eval-judge model settings.** Add to `Settings` and `.env.example`:
```python
EVAL_JUDGE_MODEL: str = "openai:gpt-4o"        # strong judge for coverage/groundedness
EVAL_SMOKE_MODEL: str = "openai:gpt-4o-mini"   # cheap judge used by --smoke
```
Both are `init_chat_model` provider-prefixed ids (OpenAI-only, §3). Rationale: LLM-judge graders are **not** graph nodes, so §2.5 ("nodes never instantiate model clients directly") does not govern them, and F9 owns the router — F8 must not modify it. The judge model is still 12-factor (env-driven) and built through a thin eval-local helper `evals/judge.py`.

**Delta 3 — dependency + CI:** add `langsmith` as an explicit dependency in `backend/pyproject.toml` (already present transitively via `langchain`; pin it explicitly). Add a new manually-triggered workflow `.github/workflows/evals-smoke.yml` (not wired into the existing `ci.yml` PR jobs — cost).

---

### Scope

1. **`evals/benchmark_topics.jsonl` — 40 topics, 10 per category.** One JSON object per line:
   ```json
   {"topic": "...", "category": "tech_comparison", "must_cover": ["point 1", "point 2", "point 3"]}
   ```
   Exact category slugs (10 each): `tech_comparison`, `market_overview`, `how_it_works`, `pricing_quant`. `must_cover` = 3–5 concrete key points a good report must address. Keep topics researchable via web search and self-contained (no private data). Deterministic file order.

2. **State + worker changes (Delta 1).**
   - `app/graph/state.py`: add `ToolCallRecord` and the `tool_calls: Annotated[list[ToolCallRecord], operator.add]` field. Update the seed-state dicts (`demo._seed_state`, `run_service._seed_state`) to include `"tool_calls": []`.
   - `app/graph/nodes/worker.py`: in the tool-execution loop, after each `tool.invoke(...)`, record one `ToolCallRecord(section_id=section.id, tool=TOOL_NAME_TO_SOURCE_TOOL[tc["name"]], urls=[...])` where `urls` are the non-empty `url` fields from that call's result items (`[]` for calculator/no-results). Return `{"drafts": [...], "usage_log": usage, "tool_calls": records}`. Rename the loop-local `tool_calls` variable (currently `ai.tool_calls`) to avoid shadowing the state key. Preserve existing determinism (§2.3 idempotent worker).

3. **`evals/judge.py` — judge model helper (Delta 2).**
   ```python
   def get_judge_model(cheap: bool = False) -> BaseChatModel:
       """Strong (EVAL_JUDGE_MODEL) or cheap (EVAL_SMOKE_MODEL) chat model for LLM-judge graders."""
   ```
   Builds via `init_chat_model(model_id, api_key=settings.OPENAI_API_KEY)` (mirror `router.get_model`'s explicit-key call). Tests monkeypatch this symbol.

4. **`evals/graders.py` — grader library.** Typed results + four graders + success rule. Every grader returns a `GraderResult`.
   ```python
   class GraderResult(BaseModel):
       name: str
       passed: bool
       score: float          # 0..1
       detail: str

   class EvalRun(BaseModel):        # everything a grader may read (built from final state, §2.4)
       topic: str
       category: str
       must_cover: list[str]
       report_md: str
       plan: list[SectionPlan]
       drafts: list[SectionDraft]
       reviews: list[Review]
       revision_counts: dict[str, int]
       usage_log: list[UsageEvent]
       tool_calls: list[ToolCallRecord]
       wall_time_s: float
       seed: int                    # per-run seed for reproducible grader sampling

   GRADER_ORDER = ["structure", "citation", "coverage", "groundedness"]  # fixed → drives first-failing taxonomy
   ```
   - `structure_grader(run) -> GraderResult` **(programmatic)** — parse `report_md` ATX headings (`^#{1,2} .+$`); pass iff order is `# {topic}`, `## Executive summary`, one-or-more `## {i}. {title}` (numbered 1..N in plan order), `## Limitations`, `## Sources`, with the three fixed headings appearing exactly once. `score` = 1.0/0.0.
   - `citation_grader(run) -> GraderResult` **(programmatic)** — three checks, all must hold:
     (a) **no dangling markers:** parse the numbered `## Sources` list → `k` entries; every `[n]` in `report_md` satisfies `1 ≤ n ≤ k`.
     (b) **≥1 source per section:** every `## {i}. {title}` body that contains a real draft contains ≥1 `[n]` marker.
     (c) **anti-fabrication:** let `ground = {u for r in run.tool_calls for u in r.urls}`; every non-empty `url` on any `draft.sources` with `tool in {"web_search","rag"}` must be in `ground`. `detail` lists offending URLs. `score` = fraction of sub-checks passed; `passed` = all three.
   - `coverage_grader(run) -> GraderResult` **(LLM judge, strong model, structured output)** — `get_judge_model()` `.with_structured_output(CoverageVerdict, include_raw=True)`, where `CoverageVerdict(covered: list[bool], notes: str)` has one bool per `must_cover` point (validate `len(covered)==len(must_cover)`; pad/truncate defensively). `score` = covered_count / len(must_cover); `passed` = `score >= 0.8`.
   - `groundedness_grader(run) -> GraderResult` **(LLM judge)** — build the candidate claim set from `run.drafts`: sentences in `draft.content_md` carrying `[n]` markers, paired with the cited `draft.sources[n-1]` (snippet). Sample **5** claim/source pairs with `random.Random(run.seed)` (fewer if under 5); for each, judge (`ClaimGrounded(supported: bool, reason: str)`, structured output) whether the claim is supported by the source `snippet`. `score` = supported / sampled (1.0 when no citable claims exist is **not** allowed — with zero sampled claims, `score = 0.0`, `passed = False`, `detail="no citable claims"`); `passed` = `score >= 0.8`.
   - `is_success(results: list[GraderResult]) -> tuple[bool, str | None]` — **fixed rule:** success iff `structure.passed AND citation.passed AND coverage.score >= 0.8 AND groundedness.score >= 0.8`. Returns `(success, first_failing)` where `first_failing` is the first name in `GRADER_ORDER` whose criterion fails (or `None` on success).

5. **`evals/run_benchmark.py` — CLI harness.**
   - Args: `--n INT` (default 40), `--category {tech_comparison,market_overview,how_it_works,pricing_quant}` (optional filter), `--seed INT` (default `42`), `--concurrency INT` (default `3`), `--smoke` (force `n=3`, `seed=42`, cheap judge via `get_judge_model(cheap=True)`), `--out DIR` (default `evals/results`).
   - `sys.path` bootstrap at top (prepend the backend root — this file's `parent.parent`) **before** importing `app.*`/`evals.*`, so the feature's `uv run python evals/run_benchmark.py …` Verify command resolves imports.
   - **Deterministic topic selection:** `select_topics(topics, n, seed, category)` — filter by category, sort by `topic` (canonical order), then `random.Random(seed).sample(pool, min(n, len(pool)))`. Same flags ⇒ same topics.
   - **Per-run driver** `run_one(topic_row, judge_cheap) -> RunResult` — mirrors `demo`: `checkpointer_cx()` → `build_graph(cp)` → seed state (unique `thread_id`) → `invoke` (pauses at approval) → `invoke(Command(resume={"action":"approve"}))` → read final state. Wrap in wall-clock timing. Per-run grader seed = stable hash of `(seed, topic)` (e.g. `int(sha256(f"{seed}:{topic}").hexdigest()[:8], 16)`). Build `EvalRun` from final state, run all four graders, compute `is_success`. On exception → a failed `RunResult` (success `False`, `first_failing="error"`, error detail) so one bad topic never aborts the batch.
   - **Concurrency:** `concurrent.futures.ThreadPoolExecutor(max_workers=concurrency)` (graph is synchronous; each run has its own `thread_id` and `checkpointer_cx()` connection). Collect results, then **sort by input topic order** before emitting (determinism independent of completion order).
   - **Trajectory stats per run (from state, §2 point 4):** `revision_loops = sum(revision_counts.values())`; `tool_calls_per_section = Counter(r.section_id for r in tool_calls)`; `cost_per_node = defaultdict(float) summing usage_log[*].cost_usd by node`; `cost_usd = sum(usage_log[*].cost_usd)`; `wall_time_s`.
   - **Outputs** under `{out}/{timestamp}/` (`timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")`):
     - `results.jsonl` — one line per run: `{topic, category, success, first_failing, grader_scores: {name: score}, grader_passed: {name: bool}, wall_time_s, cost_usd, revision_loops, tool_calls_per_section, cost_per_node}`.
     - `summary.md` — rendered from `report_template.md` (scope item 6): aggregate success rate; latency p50/p95 (`_percentile(sorted_wall_times, q)`); mean cost; **failure taxonomy table** (rows = `first_failing` grader, counts + %); **per-category breakdown** (success rate per category); run count, seed, timestamp.
   - **LangSmith experiment logging (best-effort):** when `settings.LANGSMITH_TRACING` is on, export LangSmith env (reuse `demo._enable_langsmith`'s approach) with a run-scoped project name `f"atlas-eval-{timestamp}"` so every graph run is a trace in one inspectable experiment; attach `{topic, category, seed, success}` as run metadata/tags via the `langsmith` SDK. Skipped silently when tracing is off (so `--smoke` in CI needs no LangSmith key). Print the results dir path and the aggregate success line to stdout on completion.

6. **`evals/report_template.md` — summary template.** A markdown skeleton with named placeholders the harness fills (`{timestamp}`, `{n_runs}`, `{seed}`, `{success_rate}`, `{p50_latency_s}`, `{p95_latency_s}`, `{mean_cost_usd}`, `{failure_taxonomy_table}`, `{per_category_table}`). Costs formatted monospace-friendly with 4 decimals (§8 convention: `${:.4f}`).

7. **Package wiring + deps + CI (Delta 3).**
   - Add `evals/__init__.py` so `from evals.graders import …` / `from evals.judge import …` import cleanly under pytest (which runs from `backend/`).
   - `backend/pyproject.toml`: add `langsmith` to `dependencies`.
   - `.env.example`: add `EVAL_JUDGE_MODEL`, `EVAL_SMOKE_MODEL` (with the defaults above).
   - `.github/workflows/evals-smoke.yml`: `on: workflow_dispatch`; single job (backend working-dir); `uv sync`; `uv run python evals/run_benchmark.py --smoke`; env from repo secrets `OPENAI_API_KEY`, `TAVILY_API_KEY`; upload `evals/results/**` as a build artifact. Not referenced by `ci.yml`.

8. **README:** add an "F8 — Evaluation harness" section: how to run (`uv run python evals/run_benchmark.py --n 10`), the `--smoke` mode, where results land, the fixed success definition, and how to trigger the smoke workflow.

---

### Out of scope

- Real per-role judge routing / richer pricing — **F9** (`llm/router.py`). F8 uses `EVAL_JUDGE_MODEL` directly via `evals/judge.py`.
- RAGAS retrieval-quality evaluation of the RAG tool — separate track (§3 notes RAGAS is only for the RAG retriever), not this harness.
- Full `langsmith.evaluate()` dataset/experiment objects with hosted comparison UI — deferred; F8 logs trace-per-run into one project as the trajectory-inspection mechanism (honest simplification, noted in Implementation notes).
- Frontend surfacing of eval results — no frontend feature owns this; out of scope entirely.
- Wiring evals into the per-PR `ci.yml` job — intentionally excluded (cost); only the manual `evals-smoke.yml`.

---

### Implementation notes

- **Verified against installed packages:** `langgraph>=1.0,<2.0`, `langchain>=1.0,<2.0` (structured output = `.with_structured_output(Schema, include_raw=True)` → `{"parsed","raw"}`, confirmed live in `reviewer.py`); `langsmith` already resolved in `uv.lock` transitively. `init_chat_model` needs the API key passed explicitly (pydantic-settings does not export `OPENAI_API_KEY` to the OS env) — mirror `router.get_model`.
- **Determinism boundary (AC-1):** deterministic = topic selection and grader sampling are fully reproducible given `--seed` (seeded `random.Random`; stable per-run seed derived from `(seed, topic)`). LLM/tool outputs are inherently non-deterministic — do **not** claim reproducible scores, only reproducible *inputs and sampling*. State the boundary in the README.
- **`tool_calls` reducer safety:** append-only (`operator.add`), written by parallel workers exactly like `drafts`/`usage_log` — no concurrent-scalar-write hazard. Workers must **not** write `status` (scalar). Revisions legitimately add more `ToolCallRecord`s (cumulative tool calls across a section's revisions) — that is the intended trajectory count.
- **Anti-fabrication correctness:** the grader must compare `draft.sources` URLs against `tool_calls` (the *independent* record), never against the sources themselves — otherwise a planted fake cannot be caught. The fixture test (AC-3) supplies an `EvalRun` whose `drafts[*].sources` contains a URL absent from `tool_calls` and asserts `citation_grader` fails with that URL in `detail`.
- **LLM-judge tests use fakes, never network:** monkeypatch `evals.judge.get_judge_model` to return a scripted structured-output fake (pattern from `tests/fakes.py::FakeReviewModel` — `.with_structured_output(Schema, include_raw=True)` → `{"parsed","raw"}`). Programmatic graders and selection need no model at all.
- **Cost ceiling / graceful failure:** `run_one` must catch per-run exceptions and emit a failed `RunResult`; a single topic error (or `RUN_COST_CEILING_USD` abort producing a partial report) must not crash the batch.
- **Percentiles on small n:** implement `_percentile(sorted_vals, q)` with nearest-rank (`ceil(q*n)-1`, clamped) — avoid `statistics.quantiles` edge cases at `n<2`.
- **`report_template.md` currently exists as a 60-byte stub** — overwrite it with the real template.

---

### Test plan

Backend `pytest` (`backend/tests/`), all offline (fakes/fixtures, no network):

- `test_benchmark_selection.py` — `select_topics` returns identical topics for identical `(n, seed, category)` across repeated calls, and category filtering restricts to that category. **(AC-1)**
- `test_benchmark_topics_wellformed.py` — `benchmark_topics.jsonl` parses; exactly 40 rows; 10 per category slug; every row has `topic`, valid `category`, `must_cover` of length 3–5.
- `test_structure_grader.py` — a valid F7-shaped report passes; a report with `## Sources` missing (or headings out of order) fails.
- `test_citation_grader_dangling.py` — dangling `[n]` (n > source count) fails; clean report passes.
- `test_citation_grader_antifab.py` — **planted fake-source fixture:** `EvalRun` with a `draft.sources` URL not in any `tool_calls[*].urls` → `citation_grader` fails, offending URL in `detail`. A control run where all source URLs are present in `tool_calls` passes. **(AC-3)**
- `test_coverage_grader.py` — with a faked judge returning `covered=[T,T,T,F,F]`, `score==0.6`, `passed is False`; all-true → `passed is True`.
- `test_groundedness_grader.py` — faked judge; seeded sampling picks the same claim set on repeat; `score` = supported/sampled; zero citable claims → `score==0.0, passed False`. **(AC-1)**
- `test_is_success_rule.py` — the fixed rule: passes only when structure+citation pass and coverage/groundedness ≥ 0.8; `first_failing` returns the correct earliest grader per `GRADER_ORDER`.
- `test_worker_records_tool_calls.py` — worker (with `CountingTool` fake) returns `tool_calls` with one `ToolCallRecord` per tool invocation, correct `section_id`, and URLs matching the tool result. **(Delta 1)**
- `test_summary_render.py` — given a list of `RunResult`s, the summary renderer produces a markdown string containing the failure-taxonomy table and a per-category row for each category present. **(AC-2)**

---

### Verify

From `backend/` (needs real `OPENAI_API_KEY` + `TAVILY_API_KEY`; costs a few cents):
```
uv run python evals/run_benchmark.py --n 10
```
Must print a results-dir path and an aggregate success line, and write `evals/results/{timestamp}/results.jsonl` (10 lines) + `summary.md` containing a failure-taxonomy table and a per-category breakdown.

Offline gate (no keys, runs in CI/PR):
```
uv run pytest tests/test_benchmark_selection.py tests/test_citation_grader_antifab.py \
  tests/test_structure_grader.py tests/test_is_success_rule.py \
  tests/test_worker_records_tool_calls.py tests/test_summary_render.py -q
```
All pass. Full gate: `uv run ruff check . && uv run mypy app evals && uv run pytest`.

---

### Acceptance criteria

- [ ] `evals/benchmark_topics.jsonl` has exactly 40 rows, 10 in each of `tech_comparison`, `market_overview`, `how_it_works`, `pricing_quant`, each with `topic`, `category`, and `must_cover` of 3–5 items (`test_benchmark_topics_wellformed.py`).
- [ ] **Deterministic harness:** same `--n/--seed/--category` ⇒ identical topic set; grader sampling is seeded and reproducible (`test_benchmark_selection.py`, `test_groundedness_grader.py`). **(AC-1)**
- [ ] All four graders return `GraderResult{name, passed, score, detail}`; `is_success` implements the fixed rule (structure AND citation pass, coverage ≥ 0.8, groundedness ≥ 0.8) and yields the correct `first_failing` (`test_is_success_rule.py`).
- [ ] **Anti-fabrication grader catches a planted fake-source run** via fixture, using `tool_calls` as independent ground truth (`test_citation_grader_antifab.py`). **(AC-3)**
- [ ] Worker persists a `ToolCallRecord` per tool invocation into `state["tool_calls"]`; `state.py`/§5 updated (`test_worker_records_tool_calls.py`). **(Delta 1)**
- [ ] `run_benchmark.py --n 10` emits `results.jsonl` + `summary.md`; summary contains the **failure taxonomy table** (grouped by first-failing grader) and **per-category success breakdown** (`test_summary_render.py` + Verify). **(AC-2)**
- [ ] `--smoke` runs 3 topics with the cheap judge; `.github/workflows/evals-smoke.yml` is `workflow_dispatch`-only and not referenced by `ci.yml`.
- [ ] Each run logged as a LangSmith trace under a run-scoped experiment project when `LANGSMITH_TRACING` is on (best-effort; skipped without it).
- [ ] `EVAL_JUDGE_MODEL`/`EVAL_SMOKE_MODEL` added to `Settings` + `.env.example`; `langsmith` pinned in `pyproject.toml`. **(Deltas 2, 3)**
- [ ] `ruff`, `mypy app evals`, and the full `pytest` suite pass; README "F8" section added.
