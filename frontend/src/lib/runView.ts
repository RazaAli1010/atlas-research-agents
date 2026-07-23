// Pure event-log → view-model fold (F11). This is the single source of the timeline,
// section states, cost, and writer draft, so a run renders identically whether joined
// live or reconstructed from SSE replay. Keep it pure: no Date.now(), no module state —
// the same `events` always yields the same `RunView`.
import type { AtlasEvent, Review, RunStatus, SectionDraft, SectionPlan } from '../types'

// Mirrors backend MAX_REVISIONS_PER_SECTION in backend/app/graph/state.py.
export const MAX_REVISIONS_PER_SECTION = 2

export type StageKey = 'plan' | 'approval' | 'research' | 'review' | 'write'
export type StageState = 'pending' | 'active' | 'done'
export type SectionState =
  | 'queued'
  | 'researching'
  | 'reviewing'
  | 'revising'
  | 'approved'
  | 'failed'

export const STAGE_ORDER: readonly StageKey[] = [
  'plan',
  'approval',
  'research',
  'review',
  'write',
] as const

export const STAGE_LABEL: Record<StageKey, string> = {
  plan: 'Plan',
  approval: 'Approval',
  research: 'Research',
  review: 'Review',
  write: 'Write',
}

export interface SectionView {
  id: string
  title: string
  objective: string
  state: SectionState
  revision: number // count of 'revise' reviews received for this section (0-based)
  maxRevisions: number
  lastReview: Review | null
  sourceCount: number
}

export interface RunView {
  stages: Record<StageKey, StageState>
  sections: SectionView[]
  costTotal: number
  costByNode: Record<string, number>
  writerDraft: string
  reportMd: string | null
  errorMessage: string | null
  status: RunStatus | null
}

// Which timeline stage a run status marks as *currently active*. `done`/`failed` have
// no single active stage (handled separately). Using status (not just events) as the
// active-stage driver keeps revise loops correct: status toggles research↔review.
const STATUS_ACTIVE_STAGE: Record<RunStatus, StageKey | null> = {
  planning: 'plan',
  awaiting_approval: 'approval',
  researching: 'research',
  reviewing: 'review',
  writing: 'write',
  done: null,
  failed: null,
}

interface StageSignals {
  plan: boolean
  approval: boolean
  research: boolean
  review: boolean
  write: boolean
}

function computeStages(
  status: RunStatus | null,
  entered: StageSignals,
  finished: boolean,
): Record<StageKey, StageState> {
  // A finished run: every stage that was ever entered is done, nothing pending-forever.
  if (finished) {
    return {
      plan: 'done',
      approval: 'done',
      research: 'done',
      review: 'done',
      write: 'done',
    }
  }

  // Propagate "entered" leftward so an early stage counts as reached whenever any later
  // stage was reached (covers late-join where earlier node events were missed).
  const reached: Record<StageKey, boolean> = { ...entered }
  for (let i = STAGE_ORDER.length - 2; i >= 0; i--) {
    const key = STAGE_ORDER[i]
    const next = STAGE_ORDER[i + 1]
    reached[key] = reached[key] || reached[next]
  }

  // Active stage: prefer the live status; fall back to the furthest stage reached.
  let activeIndex = status ? STAGE_ORDER.indexOf(STATUS_ACTIVE_STAGE[status] ?? ('' as StageKey)) : -1
  if (activeIndex < 0) {
    for (let i = 0; i < STAGE_ORDER.length; i++) if (reached[STAGE_ORDER[i]]) activeIndex = i
  }

  const out = {} as Record<StageKey, StageState>
  STAGE_ORDER.forEach((key, i) => {
    if (i === activeIndex) out[key] = 'active'
    else if (i < activeIndex || reached[key]) out[key] = 'done'
    else out[key] = 'pending'
  })
  return out
}

export function deriveRunView(
  events: AtlasEvent[],
  plan: SectionPlan[],
  drafts?: SectionDraft[],
): RunView {
  const sourceCountById = new Map<string, number>()
  for (const d of drafts ?? []) sourceCountById.set(d.section_id, d.sources.length)

  // Seed one SectionView per plan section, in plan order.
  const sections: SectionView[] = plan.map((p) => ({
    id: p.id,
    title: p.title,
    objective: p.objective,
    state: 'queued',
    revision: 0,
    maxRevisions: MAX_REVISIONS_PER_SECTION,
    lastReview: null,
    sourceCount: sourceCountById.get(p.id) ?? 0,
  }))
  const byId = new Map(sections.map((s) => [s.id, s]))

  const entered: StageSignals = {
    plan: false,
    approval: false,
    research: false,
    review: false,
    write: false,
  }
  const costByNode: Record<string, number> = {}
  let costTotal = 0
  let writerDraft = ''
  let reportMd: string | null = null
  let errorMessage: string | null = null
  let status: RunStatus | null = null

  for (const ev of events) {
    switch (ev.type) {
      case 'status':
        status = ev.status
        if (ev.status === 'awaiting_approval') entered.approval = true
        break
      case 'node_started':
      case 'node_finished': {
        if (ev.node === 'planner') entered.plan = true
        else if (ev.node === 'approval_gate') entered.approval = true
        else if (ev.node === 'worker') {
          entered.research = true
          if (ev.section_id) {
            const s = byId.get(ev.section_id)
            if (s) s.state = ev.type === 'node_started' ? 'researching' : 'reviewing'
          }
        } else if (ev.node === 'reviewer') entered.review = true
        else if (ev.node === 'writer') entered.write = true
        break
      }
      case 'token':
        entered.write = true
        writerDraft += ev.delta
        break
      case 'interrupt':
        entered.approval = true
        break
      case 'review': {
        entered.review = true
        const s = byId.get(ev.review.section_id)
        if (s) {
          s.lastReview = ev.review
          if (ev.review.verdict === 'approved') s.state = 'approved'
          else {
            s.state = 'revising'
            s.revision += 1
          }
        }
        break
      }
      case 'usage':
        costByNode[ev.event.node] = (costByNode[ev.event.node] ?? 0) + ev.event.cost_usd
        costTotal = ev.total_cost_usd
        break
      case 'done':
        reportMd = ev.report_md
        status = 'done'
        entered.write = true
        break
      case 'error':
        errorMessage = ev.message
        status = 'failed'
        for (const s of sections) if (s.state !== 'approved') s.state = 'failed'
        break
    }
  }

  const finished = status === 'done' || reportMd !== null
  return {
    stages: computeStages(status, entered, finished),
    sections,
    costTotal,
    costByNode,
    writerDraft,
    reportMd,
    errorMessage,
    status,
  }
}
