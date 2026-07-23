## F11 — Frontend: live run view (node timeline, sections, cost meter)

**Goal:** `RunPage` renders the agent working in real time — a graph-stage timeline, independently-progressing section cards, a running cost meter, and a streaming writer pane — reconstructed identically whether joined live or after the run has finished; `HistoryPage` lists past runs and links into it.

**Depends on:** F10 (runStore, useRunEvents, useRuns/useRun, typed client, UI kit, routing), F9 (`cost_breakdown` / `UsageEvent.node`), F6 (SSE stream + full replay on connect), F5 (interrupt payload).

### Context digest

**SSE event union consumed** (`src/types.ts`, verbatim — do not redefine):

```ts
type AtlasEvent =
  | { type: 'status'; status: RunStatus }
  | { type: 'node_started'; node: string; section_id?: string }
  | { type: 'node_finished'; node: string; section_id?: string; summary: string }
  | { type: 'token'; node: string; delta: string }
  | { type: 'interrupt'; payload: { plan: SectionPlan[] } }
  | { type: 'usage'; event: UsageEvent; total_cost_usd: number }
  | { type: 'review'; review: Review }
  | { type: 'done'; report_md: string }
  | { type: 'error'; message: string }
```

**Backend `node` string values** (verified in `backend/app/graph/builder.py` + `sse.py`): `"planner"`, `"approval_gate"`, `"worker"` (one per section, carries `section_id`), `"reviewer"`, `"writer"`. `review` events carry `Review.section_id`; `usage` events carry `UsageEvent.node`; `token` events are `node: "writer"` only (draft text is **not** streamed — only writer tokens).

**Types consumed** (`src/types.ts`): `RunStatus` (`planning | awaiting_approval | researching | reviewing | writing | done | failed`), `SectionPlan {id,title,objective,suggested_queries}`, `Review {section_id, verdict: 'approved'|'revise', score, feedback}`, `UsageEvent {node, model, input_tokens, output_tokens, cost_usd}`, `RunDetail {..., topic, status, created_at, cost_usd, plan, reviews, revision_counts, final_report_md, cost_breakdown: Record<string,number>, trace_id: string | null}` (`trace_id` added by this feature — see Context deltas).

**F10 store/hooks consumed** (do not modify their signatures):
- `useRunEvents(id): RunStreamState` — `{ events: AtlasEvent[], latestStatus, interruptPayload, reportMd, totalCost, connectionState }`. `connectionState: 'connecting'|'open'|'reconnecting'|'closed'`. `events` is the full ordered log (replayed on every (re)connect; `reset()` clears it so it is idempotent).
- `useRun(id)` (TanStack Query) → `RunDetail`; `useRuns()` → `RunSummary[]`.
- UI kit (`src/components/ui`): `Badge {status?, tone?}` (tones `accent|warn|success|danger|neutral`; `Badge status={...}` renders labelled status), `Card`, `Skeleton`, `Tabs`, `Tooltip`, `EmptyState`, `Button`, `Kbd`. Icons: `lucide-react` only.

**Design tokens** (`src/styles/theme.css`, Tailwind v4): `bg-background #0B0E14`, `bg-surface`, `bg-raised`, `border-border`, `text-text-primary`, `text-text-secondary`, `accent`, `success`, `warn`, `danger`; `font-mono` (JetBrains Mono) for costs/ids; `rounded-card`/`rounded-control`. Rules: relative timestamps with absolute on hover, costs monospace 4 decimals, skeletons not spinners, visible focus rings, no emoji-as-icons.

**Constant:** `RUN_COST_CEILING_USD = 1.50` (backend `state.py`) — CostMeter warns past 80% (`$1.20`). `MAX_REVISIONS_PER_SECTION = 2` → rev chip caps at `rev 2/2`.

**Routing** (`src/App.tsx`): `/runs/:id` → `RunPage`, `/history` → `HistoryPage` (both already wired; F11 replaces the placeholder bodies).

### Context deltas

All live per-node cost and per-section state remain **derived client-side** from the existing `events` log (no change to `ResearchState` §5, the SSE envelope, or the F10 `runStore` — its `fold` already retains the full `events` array, the sole input to derivation). `cost_breakdown` from `RunDetail` is only used to hydrate/cross-check a finished run.

**One delta: `RunDetail.trace_id: str | null`** — a new field so the frontend can deep-link the run's LangSmith trace. It touches the §7 API contract, so these edits land **before/with** F11, in order:

1. **Backend capture (prerequisite — small backend change, may be a separate commit):** the run runner records the LangSmith **root run id** per run and persists it on the runs-metadata row — `persistence/runs_repo.py` gains a nullable `trace_id` field/column, `services/run_service.py` writes it. Obtain it from the traced run (capture the root `run_id` via a `langsmith`/LangChain tracer callback — e.g. a `RunTree`/`tracing_v2_enabled` collected root id — during the `astream` in F6's stream path). `null` when `LANGSMITH_TRACING` is disabled.
2. **API (§7):** `GET /api/runs/{run_id}` → `RunDetail` gains `trace_id: str | null`. Update CLAUDE.md §7's `RunDetail` note ("full state snapshot + cost_breakdown + trace_id").
3. **Frontend contract:** add `trace_id: string | null` to `RunDetail` in `src/types.ts`.
4. **Frontend config (`.env.example`, §9):** new `VITE_LANGSMITH_BASE_URL` (path up to the project, e.g. `https://smith.langchain.com/o/<org-id>/projects/p/<project-id>`); deep-link = `` `${VITE_LANGSMITH_BASE_URL}/r/${trace_id}` ``. When either the base env or `trace_id` is absent, fall back to a static LangSmith link — **never render a dead/`href="#"` link**.

_Alternative if the LangSmith org/project must not live in frontend build config:_ expose a fully-built `trace_url: str | null` on `RunDetail` instead of `trace_id` and drop `VITE_LANGSMITH_BASE_URL`. This spec follows the requested `trace_id` shape; switch to `trace_url` only if that constraint applies.

### Scope

1. **Pure derivation module — `src/lib/runView.ts`.** One exported pure function folds the event log into an immutable view model. This is the single source of the timeline/sections/cost/report so live and replayed runs render identically and no component holds ad-hoc state.

   ```ts
   export type StageKey = 'plan' | 'approval' | 'research' | 'review' | 'write'
   export type StageState = 'pending' | 'active' | 'done'
   export type SectionState =
     | 'queued' | 'researching' | 'reviewing' | 'revising' | 'approved' | 'failed'

   export interface SectionView {
     id: string
     state: SectionState
     revision: number        // 0-based: count of 'revise' reviews received for this section
     maxRevisions: number    // = MAX_REVISIONS_PER_SECTION (2)
     lastReview: Review | null   // most recent review event for the section
     sourceCount: number     // from RunDetail.drafts[sid].sources.length when hydrated, else 0
   }

   export interface RunView {
     stages: Record<StageKey, StageState>
     sections: SectionView[]         // ordered by plan
     costTotal: number               // last usage.total_cost_usd (fallback: sum of usage costs)
     costByNode: Record<string, number>  // accumulated usage.event.cost_usd per node
     writerDraft: string             // concatenated writer token deltas
     reportMd: string | null         // set on 'done'
     errorMessage: string | null     // set on 'error'
     status: RunStatus | null
   }

   export function deriveRunView(
     events: AtlasEvent[],
     plan: SectionPlan[],            // from RunDetail.plan ?? interruptPayload.plan ?? []
     drafts?: SectionDraft[],        // from RunDetail (source counts + collapsed content)
   ): RunView
   ```

   Derivation rules (fold left-to-right; last-write-wins for scalars):
   - **Stages:** `plan` active on `node_started{planner}`, done on `node_finished{planner}`. `approval` active when `status==='awaiting_approval'` or an `interrupt` event seen; done once any `worker` node_started appears. `research` active while any section is `researching|reviewing|revising`, done when all approved (or terminal). `review` active on `node_started{reviewer}`. `write` active on `node_started{writer}` or first `token`, done on `done`. A stage is also forced `done` if a later stage is active/done (monotonic — no flicker back to pending on replay).
   - **Per-section state** keyed by `section_id`: seed every plan id as `queued`; `node_started{worker,sid}` → `researching`; `node_finished{worker,sid}` → `reviewing`; `review{sid, approved}` → `approved`; `review{sid, revise}` → `revising` and `revision += 1`; a subsequent `node_started{worker,sid}` after a revise → `researching` again. On `error`, any non-`approved` section → `failed`.
   - **Cost:** `costByNode[usage.event.node] += usage.event.cost_usd`; `costTotal = usage.total_cost_usd` (authoritative running total from backend).
   - **writerDraft:** append every `token.delta`. **reportMd/errorMessage/status:** last `done.report_md` / `error.message` / `status`.

2. **`src/components/run/NodeTimeline.tsx`** — vertical stepper of the 5 stages (Plan → Approval → Research → Review → Write) from `RunView.stages`. Active stage pulses via a subtle CSS keyframe (opacity/ring, **no `Loader2` spinner**); done stages show a `lucide-react` `Check`; pending are dimmed (`text-text-secondary`). The **Research** stage expands to one row per section (`SectionView`) showing section title + a compact state dot; a section in `revising`/`revision>0` renders a rev chip `Badge tone="warn"` reading `rev {revision}/{maxRevisions}`. Fixed row heights / reserved chip slot so rows do not reflow when an event lands.

3. **`src/components/run/SectionCard.tsx`** — one `Card` per plan section (main column grid). Shows `title`, `objective` (secondary text), a state pill (`Badge`: queued=neutral, researching/reviewing=accent, revising=warn, approved=success, failed=danger), and `source count` (monospace). When a `review` for the section is present: render `score` (monospace, 2 decimals) + a truncated `feedback` excerpt (warn color for `revise`, success for `approved`). Content stays collapsed until the run is `done`; then a "Show draft" `Tabs`/disclosure reveals `RunDetail.drafts[sid].content_md` as plain text (full rendering is F12). All optional regions occupy reserved space (skeleton lines while `queued`) — no layout shift.

4. **`src/components/run/CostMeter.tsx`** — monospace running total `$0.0000` (4 decimals) from `RunView.costTotal`, plus a thin progress bar against `RUN_COST_CEILING_USD` (import/redeclare `1.50` as a local const with a comment pointing at backend `state.py`). Bar/text switch to `warn` color past 80% (`$1.20`). Hover (`Tooltip`) shows the per-node breakdown from `RunView.costByNode` (node → `$x.xxxx`), matching the `cost_breakdown` shape. On a hydrated finished run, prefer `RunDetail.cost_breakdown` when `events` is empty.

5. **`src/components/run/ReportPane.tsx`** — during `write` (writerDraft non-empty, not yet `done`): a monospace, `whitespace-pre-wrap` draft view fed by `RunView.writerDraft`, auto-scrolled to bottom. On `done`: swap to `react-markdown` + `remark-gfm` rendering `RunView.reportMd` (basic default styling only; the polished `ReportViewer` + `SourceList` are **F12**). Reserve the pane so the swap does not shift the page.

6. **`src/components/run/ElapsedTimer.tsx`** + **`ConnectionPill`** (may live in RunPage): elapsed timer counts from `RunDetail.created_at` to now (live), freezes at the last event time when `status` is terminal; `1s` interval, formatted `m:ss`. Connection pill reflects `connectionState`: `open`→small success dot "live", `reconnecting`→amber pulsing pill "reconnecting" (never blank the page), `closed`→neutral, `connecting`→amber skeleton. Add `src/components/run/index.ts` barrel export.

7. **Rewrite `src/pages/RunPage.tsx`** — layout: header row (topic from `useRun`, `Badge status`, `ElapsedTimer`, `CostMeter`, `ConnectionPill`); a CSS grid: left column `NodeTimeline` (fixed ~260px), main column section grid (`SectionCard`s) + `ReportPane` below, right rail collapses (`hidden`/stacked) under `1100px` via a Tailwind `min-[1100px]:` breakpoint. Data: `const { events, interruptPayload, connectionState } = useRunEvents(id)`; `const { data: detail } = useRun(id)`; `const view = useMemo(() => deriveRunView(events, detail?.plan ?? interruptPayload?.plan ?? [], detail?.drafts), [events, detail, interruptPayload])`. When `status==='awaiting_approval'`: render a **"Waiting for approval"** panel with a **disabled** placeholder (the interactive approve/edit UI is **F12**). When `errorMessage`: inline `danger` banner with the message + a **"View trace in LangSmith"** deep-link built from `detail.trace_id` (`` `${VITE_LANGSMITH_BASE_URL}/r/${trace_id}` ``, `target="_blank" rel="noreferrer"`). If `trace_id` is `null` or the env is unset, fall back to a static LangSmith project link — never a dead link. Add a `src/lib/langsmith.ts` helper `langsmithTraceUrl(traceId: string | null): string | null`. Skeleton placeholders for every region before first event (no spinner for page load).

8. **Rewrite `src/pages/HistoryPage.tsx`** — `useRuns()` → table with columns: topic, `Badge status`, relative created-at (`Tooltip` absolute on hover), cost (monospace 4 decimals), success glyph (`lucide-react` `Check` success / `X` danger / `Minus` neutral for in-progress). Row click → `navigate('/runs/'+run_id)`. Real empty state via `EmptyState` (keep existing copy pattern) when list is empty; `Skeleton` rows while loading. Keep a single relative-time helper (add `src/lib/relativeTime.ts` if none exists).

### Out of scope

- Interactive plan approve/edit (approve button, plan editor) — **F12**. F11 shows only a disabled "waiting for approval" placeholder.
- Polished report rendering, `SourceList`, citation popovers, markdown typography — **F12** (`ReportViewer`). F11 uses default `react-markdown` output.
- Any backend/API/state-schema change **beyond** the `trace_id` delta above, and the demo-GIF recording asset (README note only). The LangSmith root-run-id capture is a small backend prerequisite (Context deltas §1), not part of the frontend UI scope.

### Implementation notes

- Verified installed: `react@19.2.7`, `react-router@7.18.1` (import `useParams`/`useNavigate` from `'react-router'`, not `react-router-dom`), `@tanstack/react-query@5.101.3` (object-form hooks), `react-markdown@10.1.0` + `remark-gfm@4.0.1`, `zustand@5.0.14`, `lucide-react@1.25.0`, `tailwindcss@4.3.3`, `vitest@4.1.10` + `@testing-library/react@16`.
- **Purity is the correctness contract:** `deriveRunView` must be a pure fold with no reliance on event order beyond arrival, and must produce the identical `RunView` for `[e1,e2,e3]` whether delivered incrementally (live) or all at once (replay). Because `useRunEvents` calls `reset()` and re-ingests the full log on every (re)connect, derivation must be idempotent over duplicated prefixes — never accumulate outside the fold (e.g., don't append tokens in a `useEffect`; derive `writerDraft` inside `deriveRunView`).
- **Monotonic stages:** guard against a late/replayed earlier-stage event demoting a stage already `done` (compute stage states from the max stage reached, not the last event alone) to prevent flicker/layout shift.
- **No layout shift (acceptance):** reserve space for every conditional region — fixed timeline row heights, a persistent rev-chip slot, skeleton lines in queued `SectionCard`s, a min-height report pane. Wrap section grid in `useMemo`; key `SectionCard`s by `section.id` so React reuses DOM across state transitions.
- Cost formatting: `value.toFixed(4)` in `font-mono`; timer `Math.floor` `m:ss`.
- Rev chip cap: display `Math.min(revision, maxRevisions)` so a stray extra event can't render `rev 3/2`.
- LangSmith link: read `import.meta.env.VITE_LANGSMITH_BASE_URL` (same `import.meta.env` pattern as `VITE_API_URL` in `client.ts`); `langsmithTraceUrl` returns `null` when base or `trace_id` is missing so the banner renders a static fallback link instead of a broken one. Do not hardcode the org/project id in source.

### Test plan

Vitest + Testing Library (jsdom). Feed `deriveRunView` and components synthetic `AtlasEvent[]` (extend `src/api/eventSamples.ts` patterns).

- `src/lib/runView.test.ts`:
  - **Parallel independence:** events for `s1` (`node_started worker`) and `s2` (`node_finished worker` + `review revise`) yield `sections[s1].state==='researching'` and `sections[s2].state==='revising'` simultaneously.
  - **Revision surfacing:** a `review{revise}` then a later `node_started{worker,sid}` sets `state==='researching'`, `revision===1`; a second revise → `revision===2`, capped by `maxRevisions`.
  - **Replay idempotence:** `deriveRunView(log)` deep-equals `deriveRunView([...log, ...log.slice(0,3)])`-prefix behavior — i.e. folding a duplicated-prefix log (as `reset`+replay produces) yields the same `RunView` as the single pass; `writerDraft` is not double-counted for a single-pass log.
  - **Cost:** two `usage` events accumulate `costByNode` per node and `costTotal` equals the last `total_cost_usd`.
  - **Monotonic stages:** a `node_started{planner}` arriving after `writer` is active does not move `stages.write` back to `pending`.
  - **Error:** `error` event sets `errorMessage` and flips non-approved sections to `failed`.
- `src/components/run/NodeTimeline.test.tsx`: renders 5 stage labels; a section with `revision:1` shows a `rev 1/2` chip; active stage has the pulse class and **no** `role=status`/spinner.
- `src/components/run/SectionCard.test.tsx`: `review{revise}` renders warn feedback excerpt + score; `approved` renders success; content region is absent/collapsed until `done`.
- `src/components/run/CostMeter.test.tsx`: renders `$0.0000` format; total `1.30` renders warn class (past 80%); hover exposes per-node breakdown entries.
- `src/pages/RunPage.test.tsx`: **late-join replay** — mock `useRun` returning a finished `RunDetail` and `useRunEvents` returning the full replayed `events` (done included); assert timeline shows all stages `done`, report markdown rendered, no skeletons. **awaiting_approval** — renders disabled "waiting for approval" placeholder, not an enabled approve button. **error deep-link** — `error` event + `RunDetail.trace_id='abc'` (with `VITE_LANGSMITH_BASE_URL` set) renders a "View trace in LangSmith" anchor whose `href` ends `/r/abc`; with `trace_id=null` the anchor is the static fallback (never `#`).
- `src/lib/langsmith.test.ts`: `langsmithTraceUrl('abc')` composes `${base}/r/abc`; returns `null` when base env unset or id `null`.
- `src/pages/HistoryPage.test.tsx`: `useRuns` with 2 runs renders 2 rows with status badges + monospace costs; row click navigates to `/runs/:id`; empty list renders `EmptyState`.

### Verify

```
cd frontend && npm run typecheck && npm run lint && npm run test
```
Then a live smoke test against a running backend + `npm run dev`:
```
# backend up (uvicorn) in another shell, then:
cd frontend && npm run dev
```
Set `VITE_LANGSMITH_BASE_URL` in `frontend/.env` (from `.env.example`) to your LangSmith project URL first. Open a new run with a real topic and watch on `/runs/:id`: plan stage completes → "waiting for approval" placeholder → (approve via API/F5 resume) → section rows advance **independently** → at least one section shows a `rev 1/2` chip with reviewer feedback → writer tokens stream into the report pane → pane swaps to rendered markdown on done; CostMeter increments in monospace and the elapsed timer runs. Force an error run (e.g. cost ceiling) and confirm the danger banner's "View trace in LangSmith" link opens the run's trace (`…/r/<trace_id>`). Reload the finished run's URL and confirm the full timeline reconstructs from replay with no skeleton flash. Record a healthy session as the README demo GIF.

### Acceptance criteria

- [ ] `deriveRunView` renders two sections in different live states simultaneously (parallel-independence test passes).
- [ ] Revision cycles are visible: rev chip (`rev n/2`) on the timeline row **and** reviewer feedback excerpt on the `SectionCard` (tests pass).
- [ ] Late-joining a finished run reconstructs the full timeline (all stages `done`) and rendered report purely from `GET /runs/{id}` + SSE replay (`RunPage.test.tsx` late-join test passes).
- [ ] No layout shift on event arrival — reserved slots/skeletons verified; the late-join render shows no skeletons and the streaming→rendered swap keeps pane height (visual check in Verify + no `Loader2` page-load spinner).
- [ ] CostMeter shows a monospace 4-decimal total, warns past `$1.20`, and exposes a per-node hover breakdown; `HistoryPage` lists runs and row-click navigates to the run.
- [ ] `RunDetail.trace_id` is populated by the backend and the error banner's "View trace in LangSmith" link resolves to `…/r/<trace_id>`; with a `null` `trace_id` it falls back to a static link, never a dead one (`langsmith.test.ts` + `RunPage.test.tsx` error-deep-link test pass).
- [ ] `npm run typecheck && npm run lint && npm run test` all pass; the `awaiting_approval` state shows a disabled placeholder (no approve interaction — deferred to F12).
