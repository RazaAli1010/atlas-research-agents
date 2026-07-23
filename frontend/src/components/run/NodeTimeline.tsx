// Vertical graph-stage stepper (F11 money-shot). Derived purely from RunView; the active
// stage breathes (no spinner), the Research stage expands to per-section rows, and revise
// loops surface as a "rev n/2" chip — making the LangGraph cycle visible.
import { Check } from 'lucide-react'
import { Badge } from '../ui'
import { cn } from '../../lib/cn'
import {
  STAGE_LABEL,
  STAGE_ORDER,
  type RunView,
  type SectionState,
  type SectionView,
  type StageState,
} from '../../lib/runView'

const SECTION_DOT: Record<SectionState, string> = {
  queued: 'bg-text-secondary/40',
  researching: 'bg-accent atlas-pulse',
  reviewing: 'bg-accent atlas-pulse',
  revising: 'bg-warn atlas-pulse',
  approved: 'bg-success',
  failed: 'bg-danger',
}

const SECTION_STATE_LABEL: Record<SectionState, string> = {
  queued: 'Queued',
  researching: 'Researching',
  reviewing: 'Reviewing',
  revising: 'Revising',
  approved: 'Approved',
  failed: 'Failed',
}

function StageMarker({ state }: { state: StageState }) {
  if (state === 'done') {
    return (
      <span className="grid h-5 w-5 place-items-center rounded-full bg-success/15 text-success">
        <Check size={12} strokeWidth={3} />
      </span>
    )
  }
  return (
    <span className="grid h-5 w-5 place-items-center rounded-full">
      <span
        className={cn(
          'h-2.5 w-2.5 rounded-full',
          state === 'active' ? 'bg-accent atlas-pulse' : 'bg-text-secondary/40',
        )}
      />
    </span>
  )
}

function SectionRow({ section }: { section: SectionView }) {
  const rev = Math.min(section.revision, section.maxRevisions)
  return (
    <li className="flex h-8 items-center gap-2 text-xs">
      {/* State is conveyed to assistive tech via aria-label (not visible text) so it does
          not duplicate the SectionCard's status badge. */}
      <span
        className={cn('h-2 w-2 shrink-0 rounded-full', SECTION_DOT[section.state])}
        aria-label={SECTION_STATE_LABEL[section.state]}
        role="img"
      />
      <span className="min-w-0 flex-1 truncate text-text-secondary" title={section.title}>
        {section.title}
      </span>
      {/* Reserved chip slot — fixed width keeps rows from reflowing when a chip appears. */}
      <span className="flex w-14 shrink-0 justify-end">
        {rev > 0 && (
          <Badge tone="warn" className="px-1.5 py-0 font-mono text-[10px]">
            rev {rev}/{section.maxRevisions}
          </Badge>
        )}
      </span>
    </li>
  )
}

export function NodeTimeline({ view }: { view: RunView }) {
  return (
    <ol className="space-y-1">
      {STAGE_ORDER.map((key, i) => {
        const state = view.stages[key]
        const isResearch = key === 'research'
        const showSections = isResearch && state !== 'pending' && view.sections.length > 0
        return (
          <li key={key}>
            <div className="flex items-center gap-3">
              <div className="flex flex-col items-center">
                <StageMarker state={state} />
                {i < STAGE_ORDER.length - 1 && (
                  <span className="my-0.5 h-4 w-px bg-border" aria-hidden />
                )}
              </div>
              <span
                className={cn(
                  'text-sm',
                  state === 'pending' ? 'text-text-secondary' : 'text-text-primary',
                  state === 'active' && 'font-medium',
                )}
              >
                {STAGE_LABEL[key]}
              </span>
            </div>
            {showSections && (
              <ul className="mb-1 ml-8 border-l border-border pl-3">
                {view.sections.map((s) => (
                  <SectionRow key={s.id} section={s} />
                ))}
              </ul>
            )}
          </li>
        )
      })}
    </ol>
  )
}
