// One card per plan section (F11). Live state pill + reviewer score/feedback + source count.
// Draft content stays collapsed until the run is done (draft text is never streamed).
import { useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { Badge, Card, Skeleton, type Tone } from '../ui'
import { cn } from '../../lib/cn'
import type { SectionState, SectionView } from '../../lib/runView'

const STATE_TONE: Record<SectionState, Tone> = {
  queued: 'neutral',
  researching: 'accent',
  reviewing: 'accent',
  revising: 'warn',
  approved: 'success',
  failed: 'danger',
}

const STATE_LABEL: Record<SectionState, string> = {
  queued: 'Queued',
  researching: 'Researching',
  reviewing: 'Reviewing',
  revising: 'Revising',
  approved: 'Approved',
  failed: 'Failed',
}

export interface SectionCardProps {
  section: SectionView
  /** Final draft markdown — only present (and revealable) once the run is done. */
  contentMd?: string
}

export function SectionCard({ section, contentMd }: SectionCardProps) {
  const [open, setOpen] = useState(false)
  const review = section.lastReview
  const canExpand = Boolean(contentMd)

  return (
    <Card>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-medium text-text-primary">{section.title}</h3>
          <p className="mt-0.5 line-clamp-2 text-xs text-text-secondary">{section.objective}</p>
        </div>
        <Badge tone={STATE_TONE[section.state]}>{STATE_LABEL[section.state]}</Badge>
      </div>

      {/* Reserved review/meta row — fixed min-height so a landing review event can't shift
          the grid. Skeleton line while the section is still queued. */}
      <div className="mt-3 min-h-[1.25rem] text-xs">
        {section.state === 'queued' ? (
          <Skeleton className="h-3 w-2/3" />
        ) : (
          <div className="flex items-center gap-3">
            {review ? (
              <>
                <span
                  className={cn(
                    'font-mono',
                    review.verdict === 'approved' ? 'text-success' : 'text-warn',
                  )}
                >
                  {review.score.toFixed(2)}
                </span>
                {review.feedback && (
                  <span
                    className={cn(
                      'min-w-0 flex-1 truncate',
                      review.verdict === 'approved' ? 'text-text-secondary' : 'text-warn',
                    )}
                    title={review.feedback}
                  >
                    {review.feedback}
                  </span>
                )}
              </>
            ) : (
              <span className="text-text-secondary">Awaiting review…</span>
            )}
            <span className="ml-auto shrink-0 font-mono text-text-secondary">
              {section.sourceCount} src
            </span>
          </div>
        )}
      </div>

      {canExpand && (
        <div className="mt-3 border-t border-border pt-2">
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            className="flex items-center gap-1 text-xs text-text-secondary outline-none hover:text-text-primary focus-visible:ring-2 focus-visible:ring-accent"
            aria-expanded={open}
          >
            {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            {open ? 'Hide draft' : 'Show draft'}
          </button>
          {open && (
            <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap font-mono text-xs text-text-secondary">
              {contentMd}
            </pre>
          )}
        </div>
      )}
    </Card>
  )
}
