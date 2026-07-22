// Zustand store: one SSE stream per run, many component readers.
// `ingest` folds derived fields as events arrive; `reset` rebuilds a run's slice on each
// fresh (re)connect so F6's full-history replay stays idempotent (no duplicate events).
import { create } from 'zustand'
import type { AtlasEvent, RunStatus, SectionPlan } from '../types'

export type ConnectionState = 'connecting' | 'open' | 'reconnecting' | 'closed'

export interface RunStreamState {
  events: AtlasEvent[]
  latestStatus: RunStatus | null
  interruptPayload: { plan: SectionPlan[] } | null
  reportMd: string | null
  totalCost: number
  connectionState: ConnectionState
}

// Stable empty default so readers of an unknown run never crash before the first event.
export const EMPTY_RUN_STREAM: RunStreamState = {
  events: [],
  latestStatus: null,
  interruptPayload: null,
  reportMd: null,
  totalCost: 0,
  connectionState: 'connecting',
}

interface RunStore {
  byRun: Record<string, RunStreamState>
  reset: (runId: string) => void
  ingest: (runId: string, ev: AtlasEvent) => void
  setConnectionState: (runId: string, s: ConnectionState) => void
}

function slice(byRun: Record<string, RunStreamState>, runId: string): RunStreamState {
  return byRun[runId] ?? EMPTY_RUN_STREAM
}

function fold(prev: RunStreamState, ev: AtlasEvent): RunStreamState {
  const next: RunStreamState = { ...prev, events: [...prev.events, ev] }
  switch (ev.type) {
    case 'status':
      next.latestStatus = ev.status
      break
    case 'interrupt':
      next.interruptPayload = ev.payload
      break
    case 'usage':
      next.totalCost = ev.total_cost_usd
      break
    case 'done':
      next.reportMd = ev.report_md
      next.latestStatus = 'done'
      break
    case 'error':
      next.latestStatus = 'failed'
      break
  }
  return next
}

export const useRunStore = create<RunStore>((set) => ({
  byRun: {},
  reset: (runId) =>
    set((state) => ({
      byRun: {
        ...state.byRun,
        [runId]: { ...EMPTY_RUN_STREAM, events: [] },
      },
    })),
  ingest: (runId, ev) =>
    set((state) => ({
      byRun: { ...state.byRun, [runId]: fold(slice(state.byRun, runId), ev) },
    })),
  setConnectionState: (runId, s) =>
    set((state) => ({
      byRun: {
        ...state.byRun,
        [runId]: { ...slice(state.byRun, runId), connectionState: s },
      },
    })),
}))
