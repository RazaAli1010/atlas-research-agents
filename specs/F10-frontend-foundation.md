## F10 — Frontend foundation: API layer, design system components & New Run flow

**Goal:** A production-feeling React shell — a typed API client + TanStack Query hooks, a reconnecting SSE hook feeding a Zustand store, a hand-built Tailwind UI kit (with a dev QA page), react-router routing, and a working New Run flow that creates a run and lands on `/runs/:id` in a live "connecting…" state.

**Depends on:** F6 (the `/api/runs*` HTTP surface + `AtlasEvent` SSE envelope this consumes). F1 (Vite/Tailwind/TanStack scaffold, design tokens in `styles/theme.css`).

---

### Context digest

Exact contracts this feature consumes — restated so no other file need be open.

**§7 HTTP surface (backend, already implemented in F6/F9):**

```
POST   /api/runs                 {topic}            → 201 {run_id, thread_id}
GET    /api/runs                                    → 200 RunSummary[]
GET    /api/runs/{run_id}                           → 200 RunDetail
POST   /api/runs/{run_id}/resume {action, plan?}    → 202
GET    /api/runs/{run_id}/events                    → SSE stream (AtlasEvent envelope)
GET    /api/runs/{run_id}/report.md                 → 200 markdown (F7; client builds the URL only)
GET    /api/health                                  → 200 {status:"ok"}
```

**Backend response shapes to mirror verbatim (`backend/app/api/routes_runs.py`):**

```python
CreateRunResponse: {run_id: str, thread_id: str}
RunSummary:        {run_id: str, topic: str, status: str, created_at: str, cost_usd: float}
ResumeRequest:     {action: "approve"|"edit", plan?: SectionPlan[]}
RunDetail: {run_id, thread_id, topic, status, created_at, cost_usd,
            plan: SectionPlan[], plan_approved: bool, drafts: SectionDraft[],
            reviews: Review[], revision_counts: dict[str,int], final_report_md: str,
            usage_log: UsageEvent[], cost_breakdown: dict[str,float]}
```

> Note: the *live* backend `RunDetail` already carries `cost_breakdown` (added in F9, now merged). F10 mirrors it as a **required** field so `types.ts` matches reality; F11 is where the UI *renders* it. (This is the one place F10 goes slightly beyond the raw brief's field list — see Context deltas.)

**§7 `AtlasEvent` SSE envelope — mirror VERBATIM (single source of truth for the frontend):**

```ts
type AtlasEvent =
  | { type: "status"; status: RunStatus }
  | { type: "node_started"; node: string; section_id?: string }
  | { type: "node_finished"; node: string; section_id?: string; summary: string }
  | { type: "token"; node: string; delta: string }              // writer streaming
  | { type: "interrupt"; payload: { plan: SectionPlan[] } }
  | { type: "usage"; event: UsageEvent; total_cost_usd: number }
  | { type: "review"; review: Review }
  | { type: "done"; report_md: string }
  | { type: "error"; message: string };
```

Every SSE frame is one JSON object; the SSE `event:` field is set to the event's `type` (F6 `to_sse`). **Consequence for the client:** these are *named* SSE events, so native `EventSource.onmessage` never fires — the hook must `addEventListener(<type>, …)` for each of the 9 types (see Implementation notes).

**State sub-models (from `backend/app/graph/state.py` §5) — mirror exactly:**

```python
Source:      {url, title, snippet, tool: "web_search"|"rag"|"calculator"}
SectionPlan: {id, title, objective, suggested_queries: list[str]}
SectionDraft:{section_id, content_md, sources: Source[], revision: int}
Review:      {section_id, verdict: "approved"|"revise", score: float, feedback: str}
UsageEvent:  {node, model, input_tokens: int, output_tokens: int, cost_usd: float}
```

`RunStatus = "planning"|"awaiting_approval"|"researching"|"reviewing"|"writing"|"done"|"failed"` (the state `status` literal).

**Design system (§8) — tokens already defined in `src/styles/theme.css` (do not redefine):**
Tailwind v4 `@theme` exposes: `bg-background #0B0E14`, `bg-surface #131722`, `bg-raised #1A2030`, `border-border #232B3D`, `text-text-primary #E6EAF2`, `text-text-secondary #8A94A8`, `text-accent`/`bg-accent #6E9FFF`, `text-success #4ADE80`, `text-warn #FBBF24`, `text-danger #F87171`; `rounded-card` (10px), `rounded-control` (8px); `font-sans` (Inter), `font-mono` (JetBrains Mono, already loaded in `index.html`). Rules: dark-first; skeleton loaders (never spinners for page loads); real empty states (illustration-free, text + one action); visible `focus-visible` rings; keyboard submit on forms; costs monospace, 4 decimals; timestamps relative with absolute on hover.

**Principles that bind F10:** §2.4 (`types.ts` is the single frontend contract; components import types from there only), §2.10 (no AI-boilerplate; no default Vite splash; Linear/LangSmith quality bar), §2.11 (verify installed library versions before use — do this for `react-router` after install). §8: **no component library** — `components/ui/` is hand-built on Tailwind; icons `lucide-react` only.

**Already installed (verified in `frontend/package.json` / `node_modules`):** `react 19.2`, `react-dom 19.2`, `@tanstack/react-query 5.101`, `zustand 5.0`, `lucide-react 1.25`, `tailwindcss 4.3` (+ `@tailwindcss/vite`), `typescript ~6.0`, `vite 8.1`, `vitest 4.1`, `@testing-library/react 16.3`, `jsdom`. **`react-router` is NOT installed** (Context delta 1). `main.tsx` already wraps `<App/>` in `QueryClientProvider`.

---

### Context deltas

Each is a required change accompanying implementation.

1. **Add `react-router@^7` to `frontend/package.json` dependencies** (`npm i react-router@^7`). Not currently installed; the brief requires it. v7 is the single package in "library mode" (declarative `<BrowserRouter>` + `<Routes>`); `react-router-dom` is folded into `react-router` in v7 — import router primitives from `react-router`, not `react-router-dom`. Verify the resolved version and export names against `node_modules/react-router` after install (§2.11).

2. **New env var `VITE_API_URL`** (frontend). Add `frontend/.env.example` with `VITE_API_URL=` (empty). Empty/undefined = same-origin, so the Vite dev proxy (`/api → http://localhost:8000`) handles dev with no CORS. `.env.example` committed, `.env` never (§2.8). No backend change.

3. **`types.ts` `RunDetail` includes `cost_breakdown: Record<string, number>`** (required), matching the live backend. The raw brief listed `RunDetail` without it and assigned `cost_breakdown` mirroring to F11; since the backend already returns it (F9 merged), F10 types it now to avoid a `types.ts`-vs-backend drift (§2.4). F11 still owns *rendering* it. No new backend field — this is purely a frontend-type accuracy fix.

No other shared-contract changes: no new routes, no state-schema fields, no SSE envelope drift.

---

### Scope

#### 1. `src/types.ts` — the frontend single source of truth (replace the empty stub)

Mirror §7/§5 exactly. Export every name components/hooks import:

```ts
export type RunStatus =
  | "planning" | "awaiting_approval" | "researching"
  | "reviewing" | "writing" | "done" | "failed";
export type ToolName = "web_search" | "rag" | "calculator";

export interface Source { url: string; title: string; snippet: string; tool: ToolName; }
export interface SectionPlan { id: string; title: string; objective: string; suggested_queries: string[]; }
export interface SectionDraft { section_id: string; content_md: string; sources: Source[]; revision: number; }
export interface Review { section_id: string; verdict: "approved" | "revise"; score: number; feedback: string; }
export interface UsageEvent { node: string; model: string; input_tokens: number; output_tokens: number; cost_usd: number; }

// §7 SSE envelope — VERBATIM discriminated union
export type AtlasEvent =
  | { type: "status"; status: RunStatus }
  | { type: "node_started"; node: string; section_id?: string }
  | { type: "node_finished"; node: string; section_id?: string; summary: string }
  | { type: "token"; node: string; delta: string }
  | { type: "interrupt"; payload: { plan: SectionPlan[] } }
  | { type: "usage"; event: UsageEvent; total_cost_usd: number }
  | { type: "review"; review: Review }
  | { type: "done"; report_md: string }
  | { type: "error"; message: string };
export type AtlasEventType = AtlasEvent["type"];
export const ATLAS_EVENT_TYPES = [
  "status","node_started","node_finished","token",
  "interrupt","usage","review","done","error",
] as const satisfies readonly AtlasEventType[];

// HTTP response/request shapes (§7)
export interface CreateRunResponse { run_id: string; thread_id: string; }
export interface RunSummary { run_id: string; topic: string; status: RunStatus; created_at: string; cost_usd: number; }
export interface RunDetail {
  run_id: string; thread_id: string; topic: string; status: RunStatus;
  created_at: string; cost_usd: number;
  plan: SectionPlan[]; plan_approved: boolean; drafts: SectionDraft[]; reviews: Review[];
  revision_counts: Record<string, number>; final_report_md: string;
  usage_log: UsageEvent[]; cost_breakdown: Record<string, number>;
}
export type ResumeAction =
  | { action: "approve" }
  | { action: "edit"; plan: SectionPlan[] };
```

Also add `src/api/eventSamples.ts` (or `src/test/fixtures/events.json`) — one checked-in JSON literal per `AtlasEvent` variant used by the round-trip test (acceptance).

#### 2. `src/api/client.ts` — typed fetch wrapper

```ts
const API_BASE = (import.meta.env.VITE_API_URL ?? "").replace(/\/$/, "");

export class ApiError extends Error { constructor(public status: number, message: string) { super(message); } }

async function request<T>(path: string, init?: RequestInit): Promise<T> { /* fetch, throw ApiError on !ok, parse JSON */ }

export const api = {
  createRun: (topic: string) =>
    request<CreateRunResponse>("/api/runs", { method: "POST", headers: {"content-type":"application/json"}, body: JSON.stringify({ topic }) }),
  listRuns: () => request<RunSummary[]>("/api/runs"),
  getRun: (id: string) => request<RunDetail>(`/api/runs/${id}`),
  resumeRun: (id: string, body: ResumeAction) =>
    request<void>(`/api/runs/${id}/resume`, { method: "POST", headers: {"content-type":"application/json"}, body: JSON.stringify(body) }),
  reportUrl: (id: string) => `${API_BASE}/api/runs/${id}/report.md`,
  eventsUrl: (id: string) => `${API_BASE}/api/runs/${id}/events`,
};
```

`resumeRun` returns `202` with empty body — do not `res.json()` on empty bodies (guard on `content-length`/204/202). `reportUrl`/`eventsUrl` are pure URL builders (no fetch).

#### 3. `src/api/queries.ts` — TanStack Query v5 hooks

```ts
export const runKeys = { all: ["runs"] as const, detail: (id: string) => ["runs", id] as const };

export function useRuns() { return useQuery({ queryKey: runKeys.all, queryFn: api.listRuns }); }
export function useRun(id: string) { return useQuery({ queryKey: runKeys.detail(id), queryFn: () => api.getRun(id), enabled: !!id }); }
export function useCreateRun() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: api.createRun, onSuccess: () => qc.invalidateQueries({ queryKey: runKeys.all }) });
}
export function useResumeRun(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ResumeAction) => api.resumeRun(id, body),
    onSuccess: () => { qc.invalidateQueries({ queryKey: runKeys.detail(id) }); qc.invalidateQueries({ queryKey: runKeys.all }); },
  });
}
```

#### 4. `src/stores/runStore.ts` — Zustand event store (one stream, many readers)

```ts
interface RunStreamState {
  events: AtlasEvent[];
  latestStatus: RunStatus | null;
  interruptPayload: { plan: SectionPlan[] } | null;
  reportMd: string | null;
  totalCost: number;
  connectionState: "connecting" | "open" | "reconnecting" | "closed";
}
interface RunStore {
  byRun: Record<string, RunStreamState>;
  reset: (runId: string) => void;                       // called on each fresh (re)connect — see hook
  ingest: (runId: string, ev: AtlasEvent) => void;      // append + fold derived fields
  setConnectionState: (runId: string, s: RunStreamState["connectionState"]) => void;
}
```

`ingest` folds derived fields as events arrive: `status`→`latestStatus`; `interrupt`→`interruptPayload`; `usage`→`totalCost = ev.total_cost_usd`; `done`→`reportMd = ev.report_md` and `latestStatus = "done"`; `error`→`latestStatus = "failed"`. `reset` clears a run's slice back to defaults (used on reconnect so a full replay rebuilds cleanly — see idempotency note). Use a stable empty default for unknown runs so components don't crash before first event.

#### 5. `src/api/useRunEvents.ts` — reconnecting SSE hook

```ts
export interface RunEvents {
  events: AtlasEvent[]; latestStatus: RunStatus | null;
  interruptPayload: { plan: SectionPlan[] } | null;
  reportMd: string | null; totalCost: number;
  connectionState: "connecting" | "open" | "reconnecting" | "closed";
}
export function useRunEvents(runId: string | undefined): RunEvents;
```

Behavior:
- On mount / `runId` change: `store.reset(runId)`, `setConnectionState("connecting")`, open `new EventSource(api.eventsUrl(runId))`.
- Register a listener **per event type** in `ATLAS_EVENT_TYPES` (native `EventSource` routes named events, not `message`): each `es.addEventListener(type, (e) => store.ingest(runId, JSON.parse(e.data)))`. Wrap `JSON.parse` in try/catch; drop malformed frames without tearing down.
- `onopen` → `setConnectionState("open")`.
- On terminal event (`done` or `error`): close the `EventSource`, `setConnectionState("closed")`, and **do not reconnect** (prevents an infinite replay loop, since F6 replays the whole buffer on every fresh connection).
- **Reconnect with backoff (manual, do not rely on native auto-reconnect):** on `onerror` while not terminal, close the socket, `setConnectionState("reconnecting")`, and schedule a reopen with exponential backoff `min(1000 * 2 ** attempt, 15000)` ms (attempt resets to 0 on a successful `onopen`). **Every reopen first calls `store.reset(runId)`** so the full-history replay F6 sends rebuilds state from scratch (idempotent; no duplicate events). Cap only the *delay*, not the number of attempts.
- Cleanup on unmount / `runId` change: clear any pending backoff timer and `es.close()`.
- Return the run's slice from `runStore` via a selector (so multiple components share the single stream).

#### 6. `components/ui/` — hand-built kit (Tailwind only, ≤120 lines each, `focus-visible` rings, dark-first)

Files, all typed, no component-library imports:
- `Button.tsx` — `variant: "primary"|"secondary"|"ghost"|"danger"`, `loading?` (shows a `lucide-react` `Loader2` spin + disables), `size?`. `forwardRef`, spreads `button` props.
- `Card.tsx` — `rounded-card bg-surface border border-border` container; optional `header`/`footer` slots.
- `Badge.tsx` — status-colored per §8: map each `RunStatus` → tone (`planning`/`researching`/`reviewing`/`writing`→accent, `awaiting_approval`→warn, `done`→success, `failed`→danger). Accepts `status: RunStatus` or a freeform `tone`.
- `Skeleton.tsx` — animated placeholder block (`animate-pulse bg-raised`), width/height via className.
- `Tabs.tsx` — controlled `value`/`onChange`, roving-tabindex, arrow-key nav, `role="tablist"`/`tab`/`tabpanel`, `aria-selected`.
- `Tooltip.tsx` — hover/focus tooltip; pure CSS/JS, no portal lib; `aria-describedby`.
- `EmptyState.tsx` — illustration-free: title, description, one action slot.
- `Kbd.tsx` — `font-mono` keycap for shortcut hints (e.g. `⌘`/`Ctrl`, `↵`).
- `index.ts` — barrel export.

Add `src/lib/cn.ts` — a tiny `cn(...classes)` join helper (no `clsx`/`tailwind-merge` dependency; keep it to a `.filter(Boolean).join(" ")`).

Add a **dev-only** `src/pages/DevKitPage.tsx` rendering every variant/state of every component (the visual QA page), routed at `/dev/kit` and gated by `import.meta.env.DEV`.

#### 7. Routing — `react-router` v7 (library/declarative mode)

- `src/App.tsx`: replace the current `useState` nav with a real router. Layout component `AppShell` (sidebar with `NavLink` to `/` and `/history`, `Atlas` logo — reuse current styling) rendering `<Outlet/>`. Routes:
  - `/` → `NewRunPage`
  - `/runs/:id` → `RunPage` (this feature: mounts `useRunEvents`, shows connection/status — see item 8)
  - `/history` → `HistoryPage` (placeholder empty state this feature)
  - `/dev/kit` → `DevKitPage` **only when `import.meta.env.DEV`**
  - `*` → a minimal NotFound (EmptyState + link home)
- `src/main.tsx`: wrap `<App/>` in `<BrowserRouter>` inside the existing `QueryClientProvider` (import `BrowserRouter` from `react-router`).

#### 8. Pages

- `src/pages/NewRunPage.tsx` (replace stub): centered composition — headline ("What should Atlas research?"), one large `textarea`, 3 example-topic chips (clicking fills the textarea — include the §1 example "Compare vector database pricing for a seed-stage startup" + 2 more), cost note "typical run < $0.50" (monospace `$`), submit `Button`. Submit on **⌘/Ctrl+Enter** (and the button); disabled when empty/whitespace or `useCreateRun().isPending`. On success `navigate(\`/runs/${data.run_id}\`)`. Show `ApiError` inline (danger text), not a thrown boundary.
- `src/pages/RunPage.tsx` (replace stub, **F10 scope = connection state only**): read `:id` via `useParams`, call `useRunEvents(id)`; render a header (topic if `useRun(id).data` resolved, else the id in `font-mono`), a `Badge` for `latestStatus`, and a `connectionState` indicator that shows a "connecting…" / "reconnecting…" state driven by the hook. A `Skeleton` block stands in for the timeline/report (F11/F12). **No** timeline/approval/report rendering here.
- `src/pages/HistoryPage.tsx` (replace stub): `EmptyState` placeholder ("No runs yet" + New Run action) — full list is F11+.

#### 9. `vite.config.ts` — dev proxy

Add to the existing config (keep `react()`, `tailwindcss()`, and the `test` block):

```ts
server: { proxy: { "/api": { target: "http://localhost:8000", changeOrigin: true } } },
```

SSE passes through Vite's proxy unbuffered by default; no extra flags needed.

---

### Out of scope

- **Live run visualization** — node timeline, per-section cards, cost meter reading the stream (F11). RunPage here shows only connection/status.
- **Plan approval UI** (`PlanApprovalPanel`, wiring `useResumeRun` to the interrupt payload) — F11. `useResumeRun` is *built* here but not surfaced in a page.
- **Report view** — `ReportViewer`/`SourceList`, `react-markdown` rendering, report.md download button (F12). `api.reportUrl` is built here; nothing renders it.
- **History list rendering** — F11+ (F10 ships the empty-state placeholder only).
- **Auth / error boundaries beyond inline API errors** — later.

---

### Implementation notes

- **Verify after install (§2.11):** run `npm i react-router@^7`, then confirm `node_modules/react-router/package.json` is `7.x` and that `BrowserRouter`, `Routes`, `Route`, `NavLink`, `Outlet`, `useNavigate`, `useParams` are exported from `react-router` (v7 merges `react-router-dom`). Do not import from `react-router-dom`.
- **Named SSE events are the #1 gotcha:** F6 emits `event: <type>` frames, so `EventSource.onmessage` never fires. You **must** `addEventListener` for each of the 9 `ATLAS_EVENT_TYPES`. A hook that only sets `onmessage` will silently receive nothing.
- **Reconnect idempotency (acceptance):** F6 replays its entire per-run buffer at the start of *every* connection, then live-tails. So the hook must treat each fresh socket as a full-state rebuild: `store.reset(runId)` on every (re)open, then append. This makes "reconnect renders full history" correct and duplicate-free without event IDs. Do **not** append across reconnects.
- **Stop on terminal:** close and stop reconnecting after `done`/`error`; otherwise the auto-replay would loop forever.
- **`EventSource` in tests:** jsdom has no `EventSource`. Tests inject a controllable `FakeEventSource` on `globalThis.EventSource` (constructor records URL; `.emit(type, dataObj)`, `.open()`, `.error()`, `.close()` helpers). The hook reads `globalThis.EventSource`, so no production seam is needed beyond that.
- **Base URL:** `VITE_API_URL` empty in dev → same-origin → Vite proxy. In prod (F13) it's the API origin. `import.meta.env.VITE_API_URL` is `string | undefined`; coalesce to `""`.
- **`202`/empty-body parsing:** `resumeRun` and any non-JSON response must not call `res.json()`; branch on status/`content-type`.
- **TanStack Query v5:** object-form `useQuery`/`useMutation` only (no positional args, removed in v5); `useQueryClient().invalidateQueries({ queryKey })` object form.
- **StrictMode double-invoke:** `useRunEvents`'s effect runs twice in dev StrictMode — ensure the cleanup (`es.close()` + clear timer) fully tears down so no orphan sockets/timers leak. Guard the backoff timer in a ref.
- **No emoji-as-icons / no default splash (§2.10):** icons via `lucide-react` only; the removed `App.tsx` splash must not regress into a template look.
- **Line budget:** each `components/ui/*` file ≤120 lines (acceptance-adjacent to §8 "hand-built"); factor variant maps into small records, not giant ternaries.

---

### Test plan

Vitest + `@testing-library/react` under `frontend/src/**`:

1. **`types.test.ts` — envelope round-trip (acceptance).** Import the checked-in `eventSamples` (one object per `AtlasEvent` variant). For each: assert it type-checks as `AtlasEvent` (compile-time via `satisfies`) and that a runtime discriminator narrow (`switch (ev.type)`) reaches every branch; assert `ATLAS_EVENT_TYPES` covers exactly the 9 `type` strings present in the samples (no missing/extra).
2. **`useRunEvents.reconnect.test.tsx` — survives backend restart (acceptance).** Install `FakeEventSource`. Render a probe component using `useRunEvents("r1")`. Emit `status`, `node_started`, `usage`, `interrupt`; assert `events.length === 4`, `latestStatus`, `totalCost`, `interruptPayload` folded. Fire `.error()` (no terminal yet) → assert `connectionState === "reconnecting"` and a new `FakeEventSource` is constructed after backoff (fake timers). On the new socket, **replay the same 4 + more**; assert final `events` equals the full replayed history **without duplication** (proves `reset`-on-reopen). Emit `done` → assert `reportMd` set, `connectionState === "closed"`, and no further reconnect scheduled.
3. **`ui.keyboard.test.tsx` — keyboard nav (acceptance).** Render `Tabs` and `Button`s; `Tab` moves focus, arrow keys move the active tab (roving tabindex), `Enter`/`Space` activate; assert each interactive element receives a visible focus ring class (`focus-visible:` present) and `Button` `disabled`/`loading` blocks `onClick`.
4. **`client.test.ts` — fetch wrapper.** Mock `fetch`: `createRun` POSTs `{topic}` and returns `{run_id,thread_id}`; a `500` throws `ApiError` with status; `resumeRun` on a `202` empty body resolves without `res.json()`; `reportUrl`/`eventsUrl` build `${VITE_API_URL}/api/runs/:id/…`.
5. **`NewRunPage.test.tsx` — create flow.** Render inside `QueryClientProvider` + `MemoryRouter`; mock `api.createRun`. Typing a topic + **Ctrl+Enter** calls `createRun` and navigates to `/runs/<id>`; empty/whitespace keeps submit disabled; an `ApiError` renders inline.
6. **`queries.test.ts` — invalidation.** `useCreateRun().mutateAsync` invalidates `runKeys.all`; `useResumeRun(id)` invalidates `runKeys.detail(id)` + `all` (spy on `invalidateQueries`).

---

### Verify

```bash
# terminal 1 — backend (dev, sqlite)
cd backend && uv run uvicorn app.main:app --port 8000

# terminal 2 — frontend
cd frontend && npm i react-router@^7 && npm run dev
# open http://localhost:5173
#  → NewRunPage: enter "Compare vector database pricing for a seed-stage startup",
#    press Ctrl+Enter → navigates to /runs/<id>, RunPage shows a Badge + "connecting…"→"open",
#    and events accumulate (status/node_started/…/interrupt) via the SSE hook.
#  → open http://localhost:5173/dev/kit → all UI-kit variants render per §8 (dark, dense; not a template).
#  → stop & restart the backend while on /runs/<id> → hook shows "reconnecting…", then re-renders full history.

cd frontend && npm run test && npx tsc --noEmit && npm run lint
```

Expected: all vitest suites pass; `tsc --noEmit` clean; eslint clean; the create flow lands on `/runs/:id` in a live connection state; `/dev/kit` matches §8.

---

### Acceptance criteria

- [ ] `src/types.ts` mirrors §7/§5 exactly; the checked-in JSON sample of **each** `AtlasEvent` variant parses and narrows (`types.test.ts` passes).
- [ ] `useRunEvents` registers per-type SSE listeners, folds derived state, reconnects with capped backoff, and on reconnect **replays full history without duplication** and stops on `done`/`error` (`useRunEvents.reconnect.test.tsx` passes) — satisfies "survives backend restart".
- [ ] Zero component-library imports anywhere under `src/` (grep for `@radix`, `@mui`, `@headlessui`, `shadcn`, `antd` returns nothing); UI kit passes the keyboard-nav test with visible `focus-visible` rings.
- [ ] Routing works via `react-router` v7 (`/`, `/runs/:id`, `/history`, dev-only `/dev/kit`, `*`); imports come from `react-router`, not `react-router-dom`.
- [ ] NewRunPage creates a run (⌘/Ctrl+Enter + button, example chips, cost note, disabled-when-empty) and navigates to `/runs/:id`; RunPage mounts the SSE hook and shows a connection/status state (`NewRunPage.test.tsx` passes).
- [ ] Vite dev proxy routes `/api` → `localhost:8000` (no CORS in dev); `VITE_API_URL` documented in `frontend/.env.example`.
- [ ] `npx tsc --noEmit`, `npm run lint`, and `npm run test` are all clean; `README.md` F10 section documents running the frontend (`npm i react-router@^7`, `VITE_API_URL`, `npm run dev`, `/dev/kit`).
