// One card per plan section (F11). Live state pill + reviewer score/feedback + source count.
// The full draft opens on its own page once the run is done (draft text is never streamed).
import { ChevronRight } from 'lucide-react'
import { Link } from 'react-router'
import { Badge, Card, Skeleton, type Tone } from '../ui'
import { cn } from '../../lib/cn'
import type { SectionState, SectionView } from '../../lib/runView'

const STATE_TONE: Record<SectionState, Tone> = {
  queued: 'neutral',
  researching: 'accent',
  reviewing: 'accent',
  revising: 'warn',
  unapproved: 'warn',
  approved: 'success',
  failed: 'danger',
}

const STATE_LABEL: Record<SectionState, string> = {
  queued: 'Queued',
  researching: 'Researching',
  reviewing: 'Reviewing',
  revising: 'Revising',
  unapproved: 'Not approved',
  approved: 'Approved',
  failed: 'Failed',
}

export interface SectionCardProps {
  section: SectionView
  runId: string
  /** True once a final draft exists for this section (run done) — enables the draft link. */
  contentMd?: string
}

export function SectionCard({ section, runId, contentMd }: SectionCardProps) {
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
          <Link
            to={`/runs/${runId}/sections/${section.id}`}
            className="flex items-center gap-1 text-xs text-text-secondary outline-none hover:text-text-primary focus-visible:ring-2 focus-visible:ring-accent"
          >
            <ChevronRight size={14} />
            Show draft
          </Link>
        </div>
      )}
    </Card>
  )
}
