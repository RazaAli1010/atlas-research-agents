## F12 — Frontend: plan approval (HITL) & report viewer

**Goal:** Close the human-in-the-loop — the user edits and approves the proposed plan from the browser (their edits actually change the run) — and deliver the finished report beautifully: styled markdown with clickable citation superscripts that resolve to a structured, favicon'd source list, plus copy / download / open-trace actions.

**Depends on:** F11 (`RunPage`, `deriveRunView`, `ReportPane`, `ConnectionPill`, `langsmithTraceUrl`/`LANGSMITH_HOME`, `RunDetail.trace_id`), F10 (`useResumeRun`, `useRun`, `api.reportUrl`, `ApiError`, UI kit, `types.ts`, `ATLAS_EVENT_TYPES` SSE hook), F7 (report structure contract + `merge_sections`/`_select_drafts` writer helpers + `GET /report.md`), F6 (resume route + `interrupt`-event replay), F5 (`approval_gate` resume payload shapes, `MAX_SECTIONS`).

### Context digest

Exact contracts this feature touches — restated so no other file need be open.

**Resume API (§7, backend `routes_runs.py::resume_run`, already implemented):**
```
POST /api/runs/{run_id}/resume {action, plan?} → 202
```
- `action` must be `"approve"` or `"edit"` (else **422**).
- `action:"edit"` requires a **non-empty** `plan` (else 422); the backend clamps `plan[:MAX_SECTIONS]`.
- Returns **409** `{"detail": "run is not awaiting approval"}` when `row.status != "awaiting_approval"` (already-resumed / wrong state).
- On resume the backend spawns `stream_run` into the **same** in-memory `RunStream`; the still-open EventSource (F10 closes only on `done`/`error`, and `awaiting_approval` is non-terminal) receives the continued events live.

**Frontend resume contract (`src/types.ts`, verbatim):**
```ts
export type ResumeAction =
  | { action: 'approve' }
  | { action: 'edit'; plan: SectionPlan[] }
```
**`useResumeRun(id)`** (`src/api/queries.ts`) — TanStack mutation `(body: ResumeAction) => Promise<void>`; `onSuccess` invalidates `runKeys.detail(id)` + `runKeys.all`. Rejects with **`ApiError`** (`{ status: number; message: string }`, `src/api/client.ts`) on non-2xx — inspect `err.status === 409`.

**Types consumed (`src/types.ts`):**
```ts
export interface Source { url: string; title: string; snippet: string; tool: ToolName } // ToolName = 'web_search'|'rag'|'calculator'
export interface SectionPlan { id: string; title: string; objective: string; suggested_queries: string[] }
export interface RunDetail { ...; plan: SectionPlan[]; drafts: SectionDraft[]; reviews: Review[];
  final_report_md: string; trace_id: string | null } // + sources: Source[] added by this feature (Context deltas)
```

**F11 pieces reused (do not modify signatures):**
- `src/pages/RunPage.tsx` — currently renders `ApprovalPlaceholder` when `status==='awaiting_approval'` and `<Card header="Report"><ReportPane …/></Card>` always. F12 replaces the placeholder with `PlanApprovalPanel` and swaps `ReportPane`→`ReportViewer` on `done`. Data already wired: `const { data: detail } = useRun(id)`; `const { events, interruptPayload, connectionState } = useRunEvents(id)`; `plan = detail?.plan ?? interruptPayload?.plan ?? []`; `reportMd = view.reportMd ?? detail?.final_report_md`.
- `src/lib/langsmith.ts` — `langsmithTraceUrl(traceId: string|null): string|null` (from `VITE_LANGSMITH_BASE_URL`) and `LANGSMITH_HOME`.
- `src/components/run/ReportPane.tsx` — streaming writer draft (kept for the `writing` phase; **not** used for the final `done` render anymore — see Scope 5).
- UI kit (`src/components/ui`): `Button {variant:'primary'|'secondary'|'ghost'|'danger', loading?}`, `Card {header?}`, `Badge {status?|tone?}` (tones `accent|warn|success|danger|neutral`), `Skeleton`, `Tooltip`, `EmptyState`, `Kbd`, `Tabs`. Icons: `lucide-react` only.

**Design tokens (§8, `styles/theme.css`):** `bg-surface/raised`, `border-border`, `text-text-primary/secondary`, `accent #6E9FFF`, `success/warn/danger`, `font-mono` (costs/ids), `rounded-card`(10px)/`rounded-control`(8px). Rules: visible `focus-visible` rings, keyboard submit, no emoji-as-icons, skeletons over spinners.

**Constant:** `MAX_SECTIONS = 6` (backend `state.py`; mirror as a local const in `PlanApprovalPanel` with a comment pointing at backend). The backend clamps too — the UI cap is UX, the server is the enforcer.

**Report structure contract (F7, guaranteed by `writer.py`):** `# {topic}` → `## Executive summary` → `## {i}. {title}` sections → `## Limitations` → `## Sources` (each heading exactly once, `## Sources` **last**). Body `[n]` markers are global 1-based indices; F7 guarantees **zero dangling markers** (`1 ≤ n ≤ len(sources)`). The writer's global deduped source list = `merge_sections(plan, _select_drafts(plan, drafts, reviews)[0])[1]` — index `i` ↔ marker `[i+1]`.

**Installed (verified `frontend/package.json`):** `react@19.2`, `react-router@7.18` (import from `react-router`), `@tanstack/react-query@5.101`, `react-markdown@10.1`, `remark-gfm@4.0`, `lucide-react@1.25`, `zustand@5.0`, `vitest@4.1`, `@testing-library/react@16.3`, `@testing-library/user-event@14.6`, `jsdom`. **No new dependency** (no drag-drop lib, no `rehype-raw`).

### Context deltas

**Delta 1 — new derived field `RunDetail.sources: list[Source]`** (backend + §7 + `types.ts`). The report body's `[n]` markers must link to a structured source list showing **tool origin** and **favicon** — data that the rendered `## Sources` markdown cannot losslessly carry (web_search vs rag both render as `n. [title](url)`). Deriving it in the frontend is unsafe: `RunDetail.drafts` contains **all** revisions (naive flatten double-counts/misorders) and the numbering must match the report's `[n]` exactly. So the backend exposes the writer's own global list, guaranteeing `sources[n-1]` ↔ `[n]` by construction. This mirrors F11's `trace_id` precedent (small backend prerequisite in a frontend feature). Required edits, in order (land before/with the frontend work):

1. **`backend/app/graph/nodes/writer.py`** — add a public pure helper reusing the existing functions (no logic duplication):
   ```python
   def report_sources(plan, drafts, reviews) -> list[Source]:
       """The report's global deduped source list; index i ↔ citation marker [i+1]."""
       chosen, _ = _select_drafts(plan, drafts, reviews)
       _, sources, _ = merge_sections(plan, chosen)
       return sources
   ```
2. **`backend/app/api/routes_runs.py`** — add `sources: list[Source] = []` to `RunDetail`; in `from_row_and_state`, `sources=report_sources(values.get("plan") or [], values.get("drafts") or [], values.get("reviews") or [])` (import `report_sources` from `app.graph.nodes.writer`; `Source` is already imported). Derived-on-read like `cost_breakdown` — **no new `ResearchState` field**.
3. **`CLAUDE.md §7`** — extend the `RunDetail` note: "full state snapshot + cost_breakdown + trace_id **+ sources** (the writer's global deduped source list, index i ↔ `[i+1]`; derived, never stored in `ResearchState`)".
4. **`frontend/src/types.ts`** — add `sources: Source[]` to `RunDetail`.

**Delta 2 — env-var naming reconciliation (no new var).** The raw F12 brief names `VITE_LANGSMITH_PROJECT_URL` for the "open trace" action; F11 already shipped **`VITE_LANGSMITH_BASE_URL`** + `langsmithTraceUrl(trace_id)` + `LANGSMITH_HOME`. F12 **reuses those** — it does not introduce `VITE_LANGSMITH_PROJECT_URL`. No `.env.example` change.

No other shared-contract changes: no new routes, no SSE envelope drift, no new `ResearchState` field.

### Scope

1. **`src/lib/citations.ts` — pure report/citation helpers (testable without rendering).**
   ```ts
   // Split off the trailing "## Sources" section so it isn't double-rendered (we render a
   // structured SourceList instead). Splits at the LAST "## Sources" heading (line-anchored).
   export function splitReportBody(md: string): { body: string; hadSources: boolean }

   // Rewrite bare citation markers "[n]" → markdown links "[n](#source-n)" so react-markdown
   // parses them as links we style as superscripts. Negative lookahead skips "[n](…)" (already
   // a link) and leaves "[title](url)" untouched (non-digit text). Leaves numbers in prose alone.
   export function linkifyCitations(md: string): string   // /\[(\d+)\](?!\()/g → '[$1](#source-$1)'
   ```

2. **`src/components/report/SourceList.tsx`** — `{ sources: Source[] }`. Ordered list; item `n` (1-based) gets `id="source-{n}"` (citation anchor target) and `scroll-mt-20` so anchor jumps clear the header. Each row:
   - **Favicon** for URL sources: `<img src={`https://www.google.com/s2/favicons?domain=${hostname}&sz=32`} referrerPolicy="no-referrer" onError→hide/replace with a `lucide-react` `Globe`>` (`hostname = new URL(source.url).hostname`, guarded in try/catch). Calculator sources (no url) → a `Calculator` icon instead.
   - **Title** (`source.title || hostname || source.snippet`) linking to `source.url` (`target="_blank" rel="noreferrer"`) for URL sources; **URL** shown as secondary monospace text (hostname).
   - **Tool-origin `Badge`**: `web_search`→`tone="accent"` "web", `rag`→`tone="neutral"` "rag", `calculator`→`tone="neutral"` "calc". Small `toolBadge` record, not ternaries.
   - `EmptyState`-style "No sources were cited." when `sources` is empty.

3. **`src/components/report/ReportViewer.tsx`** — `{ reportMd: string; sources: Source[]; runId: string; traceId: string | null }`.
   - Header action row (right-aligned, keyboard-reachable `Button`s / anchors, visible focus rings):
     - **Copy markdown** — `navigator.clipboard.writeText(reportMd)`; transient "Copied" state (`Check` icon, 2s).
     - **Download .md** — an `<a href={api.reportUrl(runId)} download>` (`Download` icon). Hits the F7 endpoint directly → the downloaded bytes are the backend's stored report (acceptance).
     - **Open LangSmith trace** — `<a href={langsmithTraceUrl(traceId) ?? LANGSMITH_HOME} target="_blank" rel="noreferrer">` (`ExternalLink` icon). Never a dead `#` (F11 helper guarantees fallback).
   - Body: `const { body } = splitReportBody(reportMd)`; render `<ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>{linkifyCitations(body)}</ReactMarkdown>` inside a `.prose-atlas max-w-[68ch]` container (§8: styled headings/tables/code, ~68ch measure).
   - `mdComponents.a`: when `href?.startsWith('#source-')` render `<sup><a href={href} className="citation … text-accent">{children}</a></sup>` (accent superscript that jumps to the `SourceList` item; if `sources` lacks that index, still render the sup — the anchor is a no-op, never crashes). Otherwise a normal external link (`target="_blank" rel="noreferrer"` for `http(s)`).
   - Footer: `<SourceList sources={sources} />` under a `## Sources`-equivalent heading we render ourselves.
   - Add `.prose-atlas` typography utilities in `styles/theme.css` (headings, `code`/`pre` in `font-mono` on `bg-raised`, tables with `border-border`, comfortable line-height) — hand-rolled, no `@tailwindcss/typography`.

4. **`src/components/approval/PlanApprovalPanel.tsx`** — `{ runId: string; proposedPlan: SectionPlan[] }`. Local editable state seeded once from `proposedPlan` (a deep copy).
   ```ts
   const MAX_SECTIONS = 6 // mirrors backend state.py; server clamps/validates too
   const resume = useResumeRun(runId)
   const [sections, setSections] = useState<SectionPlan[]>(() => proposedPlan.map(clone))
   const [error, setError] = useState<string | null>(null)
   const dirty = !deepEqual(sections, proposedPlan)
   ```
   Per-section editable `Card`:
   - **title** — inline `<input>` (required; blank title disables submit).
   - **objective** — `<textarea>` (auto-rows; optional).
   - **suggested_queries** — chip list: each chip has a remove `×` button; an input adds a chip on **Enter** (trims, ignores empties/dupes).
   - **reorder** — `ChevronUp`/`ChevronDown` `Button`s (swap adjacent; disabled at ends). No drag-drop dependency.
   - **delete** — `Trash2` `Button` removing the section.
   Panel controls:
   - **Add section** — appends `{ id:'', title:'', objective:'', suggested_queries:[] }`; **disabled when `sections.length >= MAX_SECTIONS`** (show `MAX_SECTIONS` cap hint).
   - **Approve plan** (primary when **not** `dirty`) → `submit({ action: 'approve' })`.
   - **Approve with edits** (primary when `dirty`) → `submit({ action: 'edit', plan: normalize(sections) })`. When `dirty`, also offer a secondary **"Discard edits & approve original"** → `submit({ action: 'approve' })` (so edits are never silently discarded by the approve button).
   - `normalize(sections)`: reassign `id = 's{index+1}'` in current order (unique, matches planner convention; backend edit path does not renumber, so the client must) and drop nothing else.
   - `submit(body)`: `resume.mutate(body, { onError })`. Disable **all** inputs + both buttons while `resume.isPending`; `loading` spinner on the active button.
   - **409 handling** (`onError`): `if (err instanceof ApiError && err.status === 409) { setError('This run was already resumed.'); queryClient.invalidateQueries({ queryKey: runKeys.detail(runId) }) }` — the refetched `status` leaves `awaiting_approval` and the panel unmounts (see Scope 6). Other errors → `setError(err.message)`.
   - On **success**: no local navigation needed — the open SSE stream advances `status` past `awaiting_approval`, so `RunPage` stops rendering the panel.
   - Submit disabled when `sections.length === 0` or any `title.trim() === ''`.
   Add `src/components/approval/index.ts` and `src/components/report/index.ts` barrels.

5. **Modify `src/pages/RunPage.tsx`** — two swaps, no data-flow changes:
   - Delete `ApprovalPlaceholder`; when `status === 'awaiting_approval'` render
     `<PlanApprovalPanel runId={id!} proposedPlan={interruptPayload?.plan ?? detail?.plan ?? []} />`.
   - Replace the report block: `reportMd !== null ? <ReportViewer reportMd={reportMd} sources={detail?.sources ?? []} runId={id!} traceId={detail?.trace_id ?? null} /> : <Card header="Report"><ReportPane writerDraft={view.writerDraft} reportMd={null} /></Card>`. (ReportPane keeps streaming the `writing` phase; the polished viewer owns the `done` render.) A **failed** run with a non-empty `reportMd`/`final_report_md` still renders `ReportViewer` (partial report preserved); the existing `ErrorBanner` + `SectionCard`s (F11) remain for the error + partial sections (edge state 3 — no new work beyond confirming both can render together).

6. **Edge/replay behavior (mostly wiring, assert in tests):**
   - **Interrupted run opened later** — F11's SSE replay re-emits the buffered `interrupt` event → `interruptPayload` repopulates and `detail.status==='awaiting_approval'`, so `PlanApprovalPanel` renders from replay (no special-casing).
   - **Failed run** — `ErrorBanner` (F11) + preserved `SectionCard`s; `ReportViewer` only if a partial report exists.

### Out of scope

- Backend approval/resume logic, `interrupt` semantics, SSE plumbing — **F5/F6** (done). F12 only calls `useResumeRun`.
- Report generation, citation numbering, dedup, `report.md` endpoint — **F7** (done). F12 renders; `report_sources` merely re-exposes F7's own computed list.
- Drag-and-drop reordering — deliberately excluded (up/down buttons; no new dependency).
- PDF/DOCX export — excluded in F7 (README note); F12 offers only copy + `.md` download.
- Live timeline / cost meter / section cards / streaming pane — **F11** (unchanged; F12 does not touch `deriveRunView`, `NodeTimeline`, `CostMeter`, `SectionCard`).

### Implementation notes

- **Citation linking without `rehype-raw`:** preprocess the markdown string (`linkifyCitations`) into real markdown links, then style via the `a` component override — avoids raw-HTML rendering and a new rehype dependency. The `(?!\()` lookahead is load-bearing: it prevents rewriting an already-linked `[1](url)` or a numeric-text link.
- **Split before linkify:** run `splitReportBody` first so the `## Sources` markdown list (which uses `1.` ordinals, not `[n]`) is never linkified or double-rendered; the structured `SourceList` replaces it.
- **`sources[n-1]` ↔ `[n]` parity is guaranteed by the backend**, not reconstructed client-side. `report_sources` recomputes from the same persisted `plan`/`drafts`/`reviews` the report was built from; `merge_sections`/`_select_drafts` are pure and deterministic, so the read-time list is identical to the one embedded in `final_report_md` (the LLM summary is the only non-determinism and does not touch the source list).
- **Id renumbering on edit is required:** `approval_gate` (F5) does **not** renumber edited plans; `fan_out` keys workers by `SectionPlan.id`. Two added sections could otherwise collide on ids → merged/duplicate timeline rows. `normalize()` reassigning `s1..sN` guarantees unique ids and clean `node_started{worker, section_id}` mapping (acceptance: removed section ⇒ no worker row).
- **After resume, the panel disappears via the stream, not a refetch:** the EventSource stays open at `awaiting_approval`; the resumed `stream_run` emits `status`/`node_started` live, `deriveRunView` advances `view.status`, and `RunPage` unmounts the panel. The 409 path is the only one that leans on `invalidateQueries` (stale-state recovery).
- **Favicon is an external image** (allowed — this is the SPA, not a CSP-restricted Artifact). Guard `new URL()` (malformed url → skip favicon), set `referrerPolicy="no-referrer"`, and `onError` fallback to a `Globe` icon so a blocked/404 favicon never leaves a broken-image glyph.
- **Clipboard in tests:** stub `navigator.clipboard.writeText` (jsdom lacks it); assert it's called with `reportMd`.
- **Keyboard-only (acceptance):** every control is a native `<input>/<textarea>/<button>/<a>` — no custom key handling needed beyond chip-add-on-Enter; rely on the kit's `focus-visible` rings. Test tab order / that submit is reachable and fires.
- **StrictMode:** `PlanApprovalPanel`'s `useState` initializer copies `proposedPlan` once; do not re-seed from props in an effect (would clobber edits on re-render). If the proposed plan identity changes (rare — only a fresh interrupt), a `key={runId}` on the panel from `RunPage` remounts it cleanly.

### Test plan

Vitest + Testing Library (jsdom); `user-event` for interactions. Wrap page/panel tests in `QueryClientProvider` + `MemoryRouter`.

- **`src/lib/citations.test.ts`** — `linkifyCitations('a [1] b')==='a [1](#source-1) b'`; leaves `[Foo](http://x)` and `[1](http://x)` untouched (lookahead); leaves `"item 1"` prose alone. `splitReportBody` returns `body` without the trailing `## Sources` block and `hadSources===true`; a report without a Sources heading returns the whole string, `hadSources===false`.
- **`src/components/report/SourceList.test.tsx`** — 3 sources (web_search url, rag url, calculator no-url): renders 3 items with `id="source-1|2|3"`; web item shows a favicon `<img>` whose `src` includes the hostname + `web` badge; rag item shows `rag` badge; calculator item shows **no** favicon img (icon) + `calc` badge; empty array → "No sources were cited."
- **`src/components/report/ReportViewer.test.tsx`** — report body containing `[1]` + one source: a `<sup>` wraps an `<a href="#source-1">`; **copy** click calls the stubbed `navigator.clipboard.writeText` with the exact `reportMd`; the download control is an `<a>` with `download` and `href` ending `/report.md`; the trace control's `href` ends `/r/<id>` when `VITE_LANGSMITH_BASE_URL` set + `traceId` given, else equals `LANGSMITH_HOME`. Assert the rendered body does **not** contain a second "## Sources" markdown list (split worked).
- **`src/components/approval/PlanApprovalPanel.test.tsx`**:
  - **Edit round-trip payload (acceptance):** 3-section plan; rename section 1's title, delete section 2, click "Approve with edits" → `resumeRun` called once with `{ action:'edit', plan }` where `plan.length===2`, ids `['s1','s2']`, `plan[0].title` = the new name. Shape satisfies `ResumeAction` edit variant (compile + runtime).
  - **Approve unedited:** with no edits, primary reads "Approve plan" and click → `resumeRun({action:'approve'})` (no `plan`).
  - **Dirty discard:** after an edit, "Discard edits & approve original" → `resumeRun({action:'approve'})`.
  - **Cap:** with 6 sections, "Add section" is `disabled`; ≤5 enables it.
  - **Validation:** blanking a title disables both submit buttons.
  - **409 handling:** `useResumeRun` mocked to reject `new ApiError(409,'run is not awaiting approval')` → panel shows "already resumed" text and calls `invalidateQueries` for `runKeys.detail`.
  - **Pending:** while pending, buttons + inputs disabled and the active button shows `loading`.
  - **Chips:** typing a query + Enter adds a chip; `×` removes it.
  - **Keyboard (acceptance):** Tab reaches title input → … → "Approve plan"; pressing the button submits (native).
- **`src/pages/RunPage.test.tsx`** (extend F11 suite): with `detail.status==='awaiting_approval'` + replayed `interrupt` event, `PlanApprovalPanel` renders (editable inputs present), **not** the old disabled placeholder. With a finished `detail` (report + `sources`) + `done` event, `ReportViewer` renders with a citation `<sup>` and the source list; `ReportPane` is not used for the final render.
- **Backend `backend/tests/test_run_detail_sources.py`** — (a) unit: `report_sources(plan, drafts, reviews) == merge_sections(plan, _select_drafts(plan, drafts, reviews)[0])[1]`. (b) async via `api_helpers`: drive a run to `done`, `GET /api/runs/{id}` → `sources` non-empty, `len(sources) == number of "## Sources" entries in final_report_md`, and every `[n]` marker in the report satisfies `1 ≤ n ≤ len(sources)` (parity). Update any `RunDetail`-shape assertion/fixtures to include `sources`.

### Verify

```bash
# backend delta + parity test
cd backend && uv run pytest -q tests/test_run_detail_sources.py && uv run ruff check app tests && uv run mypy app

# frontend
cd ../frontend && npm run typecheck && npm run lint && npm run test
```
Then the full happy path against a running backend (`uv run uvicorn app.main:app --port 8000`) + `npm run dev` (set `VITE_LANGSMITH_BASE_URL` in `frontend/.env`):
submit "Compare vector database pricing for a seed-stage startup" → on `/runs/:id` the **PlanApprovalPanel** appears → **rename** a section and **delete** one → **Approve with edits** → the timeline shows exactly the kept sections advancing (the removed section produces **no** worker row) → writer streams → the pane swaps to **ReportViewer**: click a `[n]` superscript and confirm it jumps to the matching source (favicon + tool badge) → **Download .md** and diff the file against `curl -s localhost:8000/api/runs/$RID/report.md` (identical) → **Copy markdown** and **Open LangSmith trace** work. Reload the URL mid-approval to confirm the panel reconstructs from the replayed `interrupt`. Do the entire flow with **Tab/Enter only** (no mouse).

### Acceptance criteria

- [ ] **Edited plan changes the run:** renaming + deleting a section then "Approve with edits" sends `{action:'edit', plan}` with renumbered ids, and the removed section produces no worker (timeline shows only kept sections) — `PlanApprovalPanel.test.tsx` edit-round-trip + `RunPage` render tests pass, confirmed live in Verify.
- [ ] **Citations link to correct sources:** every `[n]` in the report renders as an accent superscript link to `#source-n`, and `RunDetail.sources[n-1]` is the writer's own global source list (backend parity test passes) — `ReportViewer.test.tsx` + `SourceList.test.tsx` + `test_run_detail_sources.py` pass.
- [ ] **Downloaded file identical to backend report:** the download control targets `GET /api/runs/{id}/report.md` directly (`ReportViewer.test.tsx` asserts the `href`/`download`; Verify diffs the bytes).
- [ ] **409 already-resumed:** a resume against a non-`awaiting_approval` run shows "already resumed" and refetches (`PlanApprovalPanel.test.tsx` 409 test).
- [ ] **Add-section cap enforced in UI** at `MAX_SECTIONS=6` (button disabled) and the server clamp/422 remains authoritative (cap test).
- [ ] **Keyboard-only usable:** the whole approve/edit flow and the report actions are reachable and operable via Tab/Enter with visible focus rings (keyboard tests + Verify).
- [ ] `cd frontend && npm run typecheck && npm run lint && npm run test` and `cd backend && uv run pytest -q && ruff check && mypy app` all pass; `CLAUDE.md §7`, `frontend/src/types.ts`, and `README` (F12 section) reflect the `RunDetail.sources` delta.
