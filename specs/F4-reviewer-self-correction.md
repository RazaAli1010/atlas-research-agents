## F4 — Reviewer node & self-correction loop

**Goal:** The graph grades each section's latest draft, loops weak sections back to workers with concrete feedback, and provably terminates within the revision budget before synthesizing the report.

**Depends on:** F2 (state schema, compiled graph, planner, LLM router), F3 (worker with revision-mode payload support, `fan_out`, mechanical writer/`merge_drafts`).

### Context digest

State fields this feature reads/writes (`backend/app/graph/state.py`, SHARED CONTEXT §5 — exact names, do not rename):

```python
class Review(BaseModel):
    section_id: str
    verdict: Literal["approved", "revise"]
    score: float          # 0-1
    feedback: str         # concrete revision instructions when verdict == "revise"

class SectionDraft(BaseModel):
    section_id: str
    content_md: str       # markdown with [n] citation markers
    sources: list[Source]
    revision: int         # 0 = first draft

class ResearchState(TypedDict):
    ...
    drafts: Annotated[list[SectionDraft], operator.add]   # append reducer
    reviews: Annotated[list[Review], operator.add]        # append reducer
    revision_counts: dict[str, int]                       # section_id -> revisions used (LastValue scalar)
    usage_log: Annotated[list[UsageEvent], operator.add]  # append reducer
    status: Literal[..., "reviewing", "writing", "done", ...]
```

Constants (`state.py`): `MAX_REVISIONS_PER_SECTION = 2`, `MAX_SECTIONS = 6`.

Existing collaborators this feature wires to / upgrades:

- `worker(payload)` (`nodes/worker.py`) already supports the revision payload `{"section": SectionPlan, "topic": str, "usage_log": [...], "feedback": str, "previous_draft": SectionDraft}`. On the revision path it uses `_REVISION_SYSTEM`, and sets the new draft's `revision = previous_draft.revision + 1`. It returns `{"drafts": [draft], "usage_log": [...]}` and intentionally never writes scalar channels (`status`, `revision_counts`) because N parallel workers writing a `LastValue` channel is an illegal concurrent update.
- `merge_drafts(plan, drafts)` and `writer(state)` (`nodes/writer.py`) currently pick the **highest-revision** draft per section (`_best_drafts`) and build a deduped numbered `## Sources` list.
- `fan_out(state)` (`routing.py`) emits one `Send("worker", {"section", "topic", "usage_log"})` per plan section.
- `build_graph(checkpointer)` (`builder.py`) current topology: `START → planner → [fan_out] worker×N → writer → END`.
- LLM router (`llm/router.py`): `get_model("reviewer")` returns the default model (role ignored in F2 stub); `track_usage(node, ai_message) -> UsageEvent` reads `usage_metadata`. Structured output pattern (from `planner.py`): `get_model(role).with_structured_output(Schema, include_raw=True).invoke(msgs)` returns `{"parsed": Schema, "raw": AIMessage, "parsing_error": ...}` — `include_raw=True` is mandatory so token usage is reachable.

Target topology (SHARED CONTEXT §6): `worker×N → reviewer → (workers | writer)`, revise cycle per section capped at `MAX_REVISIONS_PER_SECTION`.

Engineering principles in force: §2.1 LangGraph 1.x only (no `langgraph.prebuilt`); §2.4 typed state, §5 is the single source of truth; §2.5 all model calls through the router; §2.6 every node logs usage; §2.7 structured outputs via Pydantic `.with_structured_output` (never regex/`json.loads` on prose).

### Context deltas

**none** — all fields (`reviews`, `revision_counts`, `status="reviewing"`) already exist in §5. This feature adds no state fields, routes, env vars, or constants.

> Interpretation note (not a contract change): the feature text says "reviewer increments `revision_counts` for revise verdicts" and routing gates on `revision_counts[sid] < MAX`. Taken literally with the increment in the reviewer *and* the gate re-reading the post-increment value, the two decisions read different snapshots and the loop under-uses the budget (1 revision when `MAX=2`) or splits the gate across two components. This spec resolves it to a **single budget gate in `route_after_review`**, with `revision_counts[sid]` defined as *revisions produced so far* = the section's highest draft `revision` (0 = only the original draft). This matches §5's `# section_id -> revisions used` comment, keeps `revision_counts` a deterministic function of `drafts` (safe under node re-execution), and lets the full budget be used. See Implementation notes.

### Scope

1. **`nodes/reviewer.py::reviewer(state) -> dict`** — single-writer node, runs after every worker wave fans in.

   - **Select sections to grade.** Group `drafts` and `reviews` by `section_id`. A section needs grading iff it has an **unreviewed latest draft**: `len(drafts_for[sid]) > len(reviews_for[sid])`. This grades exactly the newest draft per section once and never re-grades an already-settled section (approved sections stop receiving new drafts, so their counts stay equal). Reviews are produced in draft-revision order, so `reviews_for[sid][k]` always corresponds to draft `revision == k` — preserve this invariant (append one review per graded section per pass).
   - **Grade each selected section** via structured output, one call per section:

     ```python
     model = get_model("reviewer").with_structured_output(Review, include_raw=True)
     result = model.invoke([("system", _REVIEW_SYSTEM), ("human", brief)])  # brief = objective + draft.content_md + rendered sources list
     raw: AIMessage = result["raw"]
     parsed: Review = result["parsed"]
     ```

     The human message must include the section `objective`, the draft `content_md` (with its `[n]` markers), and the draft's `sources` (index, title, url, tool) so the model can spot-check that every `[n]` resolves to a listed source. `_REVIEW_SYSTEM` states the rubric: (a) objective coverage, (b) every factual claim carries a `[n]` citation, (c) no fabricated sources — cited `[n]` markers must appear in the section's sources, (d) coherence; output `score` in `[0,1]`, and `feedback` with concrete, actionable revision instructions.
   - **Normalize deterministically** (do not trust the model's `verdict` field blindly): set `section_id = sid`, and `verdict = "approved" if score >= 0.7 else "revise"`. When `verdict == "revise"` and `feedback` is empty/whitespace, substitute a concrete fallback string (feedback is never empty on a revise). Clamp `score` to `[0,1]`.
   - **Return** (append reducers + recomputed scalar):

     ```python
     return {
         "reviews": new_reviews,                 # one Review per graded section
         "usage_log": [track_usage("reviewer", r["raw"]) for r in results],
         "revision_counts": revision_counts,     # {sid: max draft revision for sid} over ALL sections graded so far
         "status": "reviewing",
     }
     ```

     Compute `revision_counts` as `{sid: max(d.revision for d in drafts_for[sid])}` for every section that has drafts. This is idempotent and independent of how many times the node runs.

2. **`routing.py::route_after_review(state) -> list[Send] | str`** — the sole budget gate and loop-termination guarantee.

   ```python
   def route_after_review(state: ResearchState) -> list[Send] | str:
       topic = state["topic"]
       plan_by_id = {s.id: s for s in state["plan"]}
       latest_review = _latest_by_section(state["reviews"])   # last Review per section_id
       latest_draft = _latest_draft_by_section(state["drafts"])  # highest-revision SectionDraft per section_id
       counts = state.get("revision_counts", {})
       usage = state.get("usage_log", [])
       sends: list[Send] = []
       for sid, review in latest_review.items():
           if review.verdict != "revise":
               continue                                        # approved section: never re-sent
           if counts.get(sid, 0) >= MAX_REVISIONS_PER_SECTION:
               continue                                        # budget exhausted: give up, do not re-send
           sends.append(Send("worker", {
               "section": plan_by_id[sid],
               "topic": topic,
               "usage_log": usage,
               "feedback": review.feedback,
               "previous_draft": latest_draft[sid],
           }))
       return sends if sends else "writer"
   ```

   Only sections whose **latest** verdict is `revise` **and** that have remaining budget are re-sent; every other section (approved, or budget-exhausted) is left alone. When no Sends are produced, route to `"writer"`.

3. **`builder.py` — wire the reviewer loop** (§6). Keep `START → planner → [fan_out] worker×N` unchanged; replace the direct `worker → writer` edge:

   ```python
   graph.add_node("reviewer", reviewer)
   graph.add_edge("worker", "reviewer")                       # all workers of a wave fan in here
   graph.add_conditional_edges("reviewer", route_after_review, ["worker", "writer"])
   graph.add_edge("writer", END)
   ```

   (The approval `interrupt()` gate between `planner` and `fan_out` is a *separate* feature and is out of scope — see Out of scope.)

4. **`nodes/writer.py` — selection upgrade + Limitations note.** Replace `_best_drafts`'s "highest revision wins" with "highest-revision **approved** draft, else best-scoring draft":

   - Pair each section's drafts to its reviews by index (revision `k` ↔ `reviews_for[sid][k]`).
   - Pick the highest-revision draft whose paired review `verdict == "approved"`; if none approved, pick the draft whose paired review has the highest `score`; if a section has drafts but no reviews, fall back to highest revision.
   - Detect **budget-exhausted-unapproved** sections: latest review `verdict == "revise"` and `revision_counts[sid] >= MAX_REVISIONS_PER_SECTION` (or no approved draft exists after budget spent). If any exist, prepend a short note right after the `# {topic}` title, before the first `## 1.` section:

     ```markdown
     > **Limitations:** the following sections did not reach the reviewer's quality bar within the revision budget: <titles>. Their best available drafts are included below.
     ```

   `merge_drafts`'s signature stays `(plan, drafts) -> (str, list[Source])`; thread the per-section chosen draft selection and the limitations set through `writer(state)` (which has access to `reviews` + `revision_counts`), keeping `merge_drafts` a pure function of the drafts it is handed.

### Out of scope

- **Human-in-the-loop approval `interrupt()` gate** between `planner` and `fan_out` (`status="awaiting_approval"` resume) — a later feature (F5 in §6). F4 leaves the `planner → fan_out → worker` edge as F3 built it.
- **Real per-role reviewer model selection** — `get_model("reviewer")` returns the F2 default; per-role routing is F9.
- **LLM-based narrative synthesis in the writer** — the writer stays a deterministic mechanical merge; F4 only changes *which* draft is chosen and adds the Limitations note.
- **RAGAS / retrieval-quality grading of sources** — the reviewer grades draft prose, not the RAG retriever (evals feature).

### Implementation notes

- **Verified versions** (installed): `langgraph>=1.0,<2.0`, `langchain>=1.0,<2.0`. Use `from langgraph.types import Send` (already the import in `routing.py`) and `StateGraph`/`add_conditional_edges` from `langgraph.graph` — never `langgraph.prebuilt` (§2.1). Structured output via `.with_structured_output(Review, include_raw=True)` returning `{"parsed", "raw", "parsing_error"}` (mirrors `planner.py`, confirmed against installed `langchain`).
- **Fan-in determinism.** In LangGraph, multiple `Send("worker", …)` in one superstep all complete before the single `reviewer` node (target of `worker → reviewer`) runs once — so the reviewer always sees the full accumulated `drafts`/`reviews`. No `interrupt()` here, so no node-re-execution idempotency concern beyond keeping `revision_counts` a pure function of `drafts` (it is).
- **Single budget gate = termination proof.** `revision_counts[sid]` (= highest draft revision) strictly increases by 1 each revision wave; `route_after_review` refuses to re-send once it reaches `MAX_REVISIONS_PER_SECTION`. Therefore each section is dispatched at most `1 (initial) + MAX_REVISIONS_PER_SECTION` times, and the reviewer runs at most `1 + MAX_REVISIONS_PER_SECTION` times regardless of how often the model says "revise". This is the loop-termination guarantee the tests assert.
- **`revision_counts` is a `LastValue` scalar** (§5, no reducer) — only the single-writer `reviewer` writes it. Workers must not (they run in parallel; concurrent scalar writes are illegal — the same reason `worker` already refuses to write `status`).
- **Review↔draft index alignment** is the writer's correctness dependency: the reviewer guarantees it by appending exactly one review per newly-drafted section per pass, in section order, so review index `k` always pairs with draft `revision k`.
- **Test doubles.** Extend `tests/fakes.py` with a structured-output fake for the reviewer (mirroring the inline `_FakeModel/_FakeStructuredModel` in `test_planner.py`), e.g. `FakeReviewModel(scripted_reviews)` whose `.with_structured_output(Review, include_raw=True).invoke(...)` returns `{"parsed": Review(...), "raw": ai("")}`. For the always-revise termination test, script it to always return `score < 0.7`.

### Test plan

Add `backend/tests/test_reviewer.py`, `test_route_after_review.py`, and extend `test_writer_merge.py` / add `test_graph_review_loop.py`:

- **`test_reviewer_grades_only_unreviewed_latest`** — state with two sections, one already approved (equal draft/review counts) and one with a fresh unreviewed draft → reviewer returns exactly one new `Review` (for the fresh section), one `usage_log` event, `status == "reviewing"`.
- **`test_reviewer_normalizes_verdict_and_feedback`** — model returns `score=0.6` → `verdict == "revise"` and non-empty `feedback`; `score=0.9` → `verdict == "approved"`. (Rubric threshold 0.7 enforced server-side.)
- **`test_reviewer_sets_revision_counts_from_drafts`** — section with drafts at revisions {0,1} → `revision_counts[sid] == 1`.
- **`test_route_revise_within_budget_sends_worker`** — latest review `revise`, `revision_counts[sid]=0` → one `Send("worker", …)` carrying `feedback` and `previous_draft` (the highest-revision draft); assert payload keys.
- **`test_route_only_failing_sections_resent`** — one approved + one revise section → exactly one Send, for the revise section; approved section not sent.
- **`test_route_budget_exhausted_goes_to_writer`** — latest review `revise` but `revision_counts[sid] == MAX_REVISIONS_PER_SECTION` → returns `"writer"`, no Sends.
- **`test_loop_terminates_bounded`** (the termination guarantee) — build the full graph with a stub worker and an **always-revise** fake reviewer wrapped to count invocations; run to completion → graph reaches `writer`/`status=="done"`, reviewer invoked **≤ `1 + MAX_REVISIONS_PER_SECTION`** times, and `revision_counts[sid] == MAX_REVISIONS_PER_SECTION` for the revised section.
- **`test_writer_prefers_approved_over_higher_revision`** — section has an approved rev-1 draft and a later rev-2 revise draft → report body contains the rev-1 (approved) content.
- **`test_writer_adds_limitations_note`** — a section exhausted its budget unapproved → report begins with `# {topic}` then the `> **Limitations:**` note listing that section's title, before `## 1.`.

### Verify

```
cd backend && uv run pytest tests/test_reviewer.py tests/test_route_after_review.py tests/test_graph_review_loop.py tests/test_writer_merge.py -q
```

All pass — in particular `test_loop_terminates_bounded` proves the always-revise graph still halts. Then a live demo showing at least one revise→improve cycle in the LangSmith trace (`LANGSMITH_TRACING=true`):

```
cd backend && uv run python -m app.graph.demo "Give exact 2026 per-GB monthly storage prices for Pinecone, Weaviate, and Qdrant with a break-even table"
```

Output must show `Drafts produced` > number of plan sections (evidence at least one section was re-drafted), the final report includes the revised section, and the LangSmith `atlas` project trace shows `worker → reviewer → worker → reviewer → writer`.

### Acceptance criteria

- [ ] The revise cycle exists (`worker → reviewer → worker`) and is provably bounded — `test_loop_terminates_bounded` passes with an always-revise reviewer, reviewer invoked ≤ `1 + MAX_REVISIONS_PER_SECTION` times.
- [ ] Reviews are structured `Review` instances via `.with_structured_output` (no regex/JSON-on-prose); `verdict` is `revise` iff `score < 0.7`; `feedback` is non-empty whenever `verdict == "revise"`.
- [ ] Only failing sections re-run — approved sections are never re-sent to a worker nor re-graded (`test_route_only_failing_sections_resent`, `test_reviewer_grades_only_unreviewed_latest`).
- [ ] `revision_counts[sid]` accurately equals the number of revisions produced for each section after the loop (`test_reviewer_sets_revision_counts_from_drafts`, termination test).
- [ ] Reviewer appends one `UsageEvent` per graded section to `usage_log`.
- [ ] The writer selects the highest-revision approved draft (else best-scoring) per section and prepends a `> **Limitations:**` note when any section exhausted its budget unapproved.
- [ ] Topology matches §6; no import from `langgraph.prebuilt`; `mypy` and `ruff` clean; `uv run pytest` green.
