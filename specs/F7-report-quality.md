## F7 — Report quality: citations, dedup & export

**Goal:** The writer emits an analyst-grade report — global citation numbering, deduped sources, an LLM-written executive summary, and a fixed heading skeleton — with zero dangling `[n]` markers, and the report is downloadable as a `.md` file.

**Depends on:** F3 (writer node, `merge_drafts`, `Source`/`SectionDraft` construction in `worker._collect`), F5 (`RunsRepo`, `report_md` column, `RunService`), F6 (`routes_runs.py`, SSE `token` plumbing, `RunDetail`).

### Context digest

The contracts F7 must not drift from (exact names quoted from the shared context and code):

- **State schema (`app/graph/state.py`, §5)** — used verbatim:
  - `Source(url: str, title: str, snippet: str, tool: Literal["web_search","rag","calculator"])`; docstring already says `snippet` is "<=300 chars, our own summary — never long verbatim quotes".
  - `SectionDraft(section_id, content_md, sources: list[Source], revision)`; `content_md` carries local `[n]` markers where `n` is 1-based into that draft's own `sources`.
  - `SectionPlan(id, title, objective, suggested_queries)`; `Review(section_id, verdict, score, feedback)`; `UsageEvent(node, model, input_tokens, output_tokens, cost_usd)`.
  - `ResearchState.final_report_md: str`, `status` literal (writer sets `"done"`).
  - Constants: `MAX_REVISIONS_PER_SECTION = 2`.
- **Writer today (`app/graph/nodes/writer.py`, F3)** already: picks the best draft per section (`_select_drafts` → highest-revision approved, else best-scoring, else latest; flags budget-exhausted sections), remaps local→global `[n]` via `merge_drafts`, dedupes sources by `_source_key` (URL, or `calc:{expr}` for calculator), and prints a `## Sources` list. Two gaps F7 fills: (a) unresolved markers currently pass through via `_remap`'s `match.group(0)` fallback (they can dangle or collide with a valid global index); (b) *Limitations* is a blockquote prepended above the sections, and there is **no** executive summary.
- **Export route (API contract §7, marked "implemented in F7"):** `GET /api/runs/{run_id}/report.md → 200 markdown download (Content-Disposition: attachment)`.
- **Persistence:** `RunsRepo` already has a `report_md TEXT` column; `RunService.stream_run`/`_invoke_resume` already persist `values.get("final_report_md")` into it on every settle. `RunRow.report_md: str | None`. So "store final markdown in the run row" is already wired — F7 only reads it back in the export route.
- **SSE (`app/api/sse.py`, F6):** `chunk_to_events` `messages` mode already emits `TokenEvent(node="writer", delta=...)` for chunks whose `metadata["langgraph_node"] == "writer"`. This is dormant only because the F3 writer makes no LLM call; F7's executive-summary call lights it up automatically (no SSE change). `DoneEvent.report_md` still carries the authoritative full report.
- **Router (`app/llm/router.py`, §2.5):** all LLM calls go through `get_model(role)` + `track_usage(node, ai)`. Writer must use `get_model("writer")`, never instantiate a client.
- **Principles:** §2.7 structured outputs for structured data (the exec summary is free prose, so a plain streamed `.invoke` is correct — not `.with_structured_output`); §2.6 every node logs usage; writer does not call `interrupt()` so re-execution concerns don't apply.
- **Test doubles (`tests/fakes.py`):** `FakeModel([ai(...)])` returns scripted `AIMessage`s (`.invoke`, `.bind_tools`), `ai(content=...)` carries `usage_metadata` `track_usage` can read. `tests/api_helpers.py::patch_models` monkeypatches each node module's `get_model`.

### Context deltas

One minor addition to §5's constants + a validator (enforcing an existing stated bound, no field renamed/added):

- Add constant `MAX_SNIPPET_CHARS = 300` to `app/graph/state.py` (§5 "Hard limits" block) and a Pydantic v2 `field_validator("snippet")` on `Source` that truncates to `MAX_SNIPPET_CHARS`. This makes the "≤300 chars" guarantee structural — true for **every** `Source` regardless of construction site — rather than relying on `worker._snippet` alone. Update §5's constant list to mention `MAX_SNIPPET_CHARS = 300`.

Everything else fits the existing contracts (no new state field, no new route beyond the already-specced export route, no env var).

### Scope

1. **Snippet hygiene (`app/graph/state.py`).** Add `MAX_SNIPPET_CHARS = 300` and:
   ```python
   from pydantic import field_validator
   class Source(BaseModel):
       ...
       @field_validator("snippet")
       @classmethod
       def _clamp_snippet(cls, v: str) -> str:
           return v[:MAX_SNIPPET_CHARS]
   ```
   Leave `worker._snippet` (whitespace-collapse + slice) as-is; the validator is the backstop. Point `worker._SNIPPET_CHARS` at the new constant (`from app.graph.state import MAX_SNIPPET_CHARS`) so there is one source of truth.

2. **Citation pipeline — strip unresolved markers (`app/graph/nodes/writer.py`).** Refactor the merge so remapping *strips* any marker not present in a section's local→global map instead of passing it through. Replace `merge_drafts` with a section-body builder that returns a stripped count:
   ```python
   _CITATION_RE = re.compile(r"\s?\[(\d+)\]")   # optional leading space so removal leaves clean prose

   def merge_sections(
       plan: list[SectionPlan], drafts: list[SectionDraft]
   ) -> tuple[str, list[Source], int]:
       """Numbered section bodies in plan order + deduped global sources + count of
       stripped (unresolvable) markers. Local [n] → global [m]; a marker whose local
       n is not in the draft's own source map is removed and counted."""
   ```
   - Dedup/global indexing logic stays (`_source_key`, `_global_idx`).
   - In the per-section `re.sub`, if `local in mapping` → `[global]`; else return `""` (strip, incl. the optional leading space) and increment a `stripped` counter.
   - Return only the joined `## {i}. {title}` bodies — **no** `## Sources` block here (assembler owns section ordering; Sources are rendered separately in step 4).

3. **Executive summary — LLM, streamed (`app/graph/nodes/writer.py`).** New pure-ish helper that takes an injected model so it's testable:
   ```python
   _WRITER_SYSTEM = (
       "You are the writer for an autonomous research agent. Write a tight executive "
       "summary of the research below in at most 150 words. Plain prose, no headings, "
       "no bullet lists, and do NOT include any [n] citation markers. State the key "
       "findings and the bottom-line recommendation."
   )
   def _executive_summary(topic, sections_md, model) -> tuple[str, UsageEvent]:
       ai = model.invoke([SystemMessage(_WRITER_SYSTEM),
                          HumanMessage(f"Topic: {topic}\n\n{sections_md}")])
       return _cap_words(ai.content, 150), track_usage("writer", ai)
   ```
   - `_cap_words(text, 150)`: collapse to plain text, split on whitespace, keep first 150 words (append `…` if truncated) — enforces the ≤150 contract regardless of the model.
   - The node calls `get_model("writer")` and invokes it directly inside `writer(state)` so LangGraph's `messages` stream captures the tokens (dormant F6 `TokenEvent` path activates).

4. **Report assembler — fixed structure contract (`app/graph/nodes/writer.py`).** Deterministic function producing the exact skeleton:
   ```python
   def assemble_report(topic, summary_md, sections_md, limitations_md, sources) -> str:
       # "# {topic}\n\n## Executive summary\n{summary}\n\n{sections}\n\n
       #  ## Limitations\n{limitations}\n\n## Sources\n{rendered sources}"
   ```
   - **Order is fixed and every heading always present:** `# {topic}` (H1) → `## Executive summary` → `## {i}. {title}` sections in plan order → `## Limitations` → `## Sources`.
   - `## Sources` rendering reuses today's per-tool formatting (calculator → `n. {snippet} _(calculator)_`; URL → `n. [{title or url}]({url})`; else title/snippet). Empty → `_No sources were cited._`.
   - **Limitations body** composes up to two sentences and falls back to `None.` when empty:
     - budget-exhausted sections (from `_select_drafts`'s `exhausted` set): "The following sections did not reach the reviewer's quality bar within the revision budget: {titles}. Their best available drafts are included."
     - stripped markers (`stripped > 0`): "{stripped} citation marker(s) that did not resolve to a source were removed."
   - **Post-write validation:** after assembling `summary_md + sections_md`, assert every `[n]` is in `1..len(sources)`; strip any that are not (belt-and-suspenders over step 2) and fold their count into the stripped total feeding Limitations. Guarantees **zero dangling markers** in the emitted report.

5. **Rewrite `writer(state)` (`app/graph/nodes/writer.py`).** Orchestrate: `_select_drafts` → `merge_sections` → `_executive_summary` (LLM) → build limitations text from `exhausted` + stripped count → `assemble_report`. Return `{"final_report_md": report, "status": "done", "usage_log": [usage_event]}` (adds `usage_log` — the exec-summary call must be tracked; the channel's reducer appends it).

6. **Export endpoint (`app/api/routes_runs.py`).** Add before/after the existing `/runs/{run_id}` routes (no path conflict — extra segment):
   ```python
   @router.get("/runs/{run_id}/report.md")
   async def download_report(run_id: str, request: Request) -> Response:
       svc = _service(request)
       row = svc._repo.get(run_id)
       if row is None:
           raise HTTPException(status_code=404, detail="run not found")
       report = row.report_md
       if not report:                               # fall back to live state
           report = (await svc.get_state_values(row.thread_id)).get("final_report_md") or ""
       if not report:
           raise HTTPException(status_code=409, detail="report not ready")
       return Response(
           content=report,
           media_type="text/markdown; charset=utf-8",
           headers={"Content-Disposition": f'attachment; filename="atlas-report-{run_id}.md"'},
       )
   ```

7. **Docs (`backend/README.md`).** Add an "F7 — report quality & export" section: the structure contract, the `GET /api/runs/{id}/report.md` download, and a note that **PDF export is deliberately out of scope**. Replace the F6 "Writer `token` events are dormant" limitation bullet — F7 activates it (the writer now streams the executive summary).

### Out of scope

- PDF / DOCX export — deliberately excluded (README note). No owning feature.
- Narrative synthesis of section bodies (rewriting/merging prose across sections) — writer still concatenates section bodies mechanically; only the *summary* is LLM-written.
- Per-role model routing for the writer — F9 owns `get_model` internals; F7 uses the stubbed single model behind `get_model("writer")`.
- Frontend rendering of the report / a download button — F12 (report viewer) owns UI; F7 ships the backend endpoint only.

### Implementation notes

- Verified installed: **Pydantic v2** (`pydantic>=2`) → `field_validator` + `@classmethod` is the correct v2 form. **LangGraph 1.x / LangChain 1.x** — writer's LLM call mirrors the existing `worker`/`reviewer` pattern (`get_model` + `SystemMessage`/`HumanMessage` + `track_usage`); no `langgraph.prebuilt` (§2.1).
- **Determinism split:** keep `merge_sections`, `assemble_report`, `_cap_words`, and marker validation as **pure** functions (no model) so citation/structure tests run without network. Only `_executive_summary` and `writer(state)` touch the model — tests patch `writer.get_model` (as `api_helpers.patch_models` does for other nodes) or call `_executive_summary(..., FakeModel([...]))` directly.
- **Marker stripping regex:** `\s?\[(\d+)\]` removes an optional single leading space with the marker so `"low [9]."` → `"low."` (no double space). Validate the whole `summary + sections` block (the `## Sources` list uses `1.` ordinals, not `[n]`, so it is not touched).
- **Strip-then-collide bug being fixed:** the F3 `_remap` left unknown local markers verbatim, so a hallucinated `[9]` could survive and coincidentally match a valid global source. Stripping at remap time (step 2) plus the range assertion (step 4) closes this.
- **Existing tests that must be updated** (behavior intentionally changed): `tests/test_writer_merge.py` — `merge_drafts` is replaced by `merge_sections` (3-tuple, no inline `## Sources`); the `writer(...)` tests must monkeypatch `writer.get_model` (it now calls an LLM); `test_writer_adds_limitations_note` must assert Limitations is a `## Limitations` **section before `## Sources`**, not a top-of-report blockquote.
- **Idempotency:** writer performs no `interrupt()` and no external side effects before returning; regenerating the (non-deterministic) summary on a re-run is acceptable.

### Test plan

New/updated tests under `backend/tests/` (each asserts one behavior):

- `test_writer_renumber_three_sections` — 3 sections with overlapping source URLs → global source list deduped to the unique URLs; each section's local markers remap to the correct global indices in plan order (extends the existing 2-section case).
- `test_writer_strips_unresolved_markers` — a draft whose `content_md` cites `[5]` with only 1 source → the `[5]` is absent from the report, `max([n]) <= len(sources)`, and `## Limitations` mentions the removed marker(s).
- `test_report_structure_contract` — run `writer(state)` with `get_model` patched to a `FakeModel` → parse `^#{1,2} ` headings and assert exact order: `# {topic}`, `## Executive summary`, `## 1. …`/`## 2. …` in plan order, `## Limitations`, `## Sources` (each present exactly once).
- `test_exec_summary_word_cap` — `_executive_summary(topic, sections, FakeModel([ai("word "*300)]))` → result has ≤150 words.
- `test_source_snippet_clamped` — `Source(url="u", title="t", snippet="x"*500, tool="web_search").snippet` has length 300.
- `test_export_report_headers` (async, via `api_helpers`) — drive a run to `done`, `GET /api/runs/{id}/report.md` → `200`, `Content-Disposition` starts `attachment; filename="atlas-report-`, `content-type` starts `text/markdown`, body == the run's stored report; unknown id → `404`; a run with no report yet → `409`.
- Update `test_writer_merge.py` per Implementation notes (new `merge_sections` arity + patched writer model + Limitations-as-section).

### Verify

```bash
cd backend
uv run pytest -q tests/test_writer_merge.py tests/test_writer_renumber_three_sections.py \
  tests/test_writer_strips_unresolved_markers.py tests/test_report_structure_contract.py \
  tests/test_exec_summary_word_cap.py tests/test_source_snippet_clamped.py \
  tests/test_export_report_headers.py
uv run ruff check app tests && uv run mypy app
```
All selected tests pass, ruff/mypy clean. Manual end-to-end (needs `OPENAI_API_KEY`/`TAVILY_API_KEY`): start a run, approve the plan (F6 demo block), then
```bash
curl -s -D - localhost:8000/api/runs/$RID/report.md -o report.md   # shows Content-Disposition: attachment
```
Open `report.md`: an H1 title, a `## Executive summary`, sections in plan order, `## Limitations`, and a single deduped `## Sources` list whose numbering matches the `[n]` markers in the body.

### Acceptance criteria

- [ ] **Zero dangling citation markers:** `test_writer_strips_unresolved_markers` + `test_writer_renumber_three_sections` prove every `[n]` in the emitted report resolves to a `## Sources` entry (`max marker ≤ len(sources)`), unresolved markers stripped.
- [ ] **Duplicate URLs collapse to one source entry** across sections (`test_writer_renumber_three_sections`).
- [ ] **Report follows the structure contract exactly** — `# title` → `## Executive summary` → sections in plan order → `## Limitations` → `## Sources`, each once (`test_report_structure_contract`).
- [ ] Executive summary is present and ≤150 words (`test_exec_summary_word_cap`; `## Executive summary` heading in structure test).
- [ ] `GET /api/runs/{id}/report.md` returns `200` with `Content-Disposition: attachment` and the stored markdown (`test_export_report_headers`).
- [ ] Every stored `Source.snippet` is ≤300 chars structurally (`test_source_snippet_clamped`).
- [ ] `ruff`, `mypy`, and the full `pytest` suite (including the updated writer/merge tests) pass.
