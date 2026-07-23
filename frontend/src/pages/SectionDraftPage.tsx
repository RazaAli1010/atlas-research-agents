// Dedicated draft page for a single section. The run page's section cards link here once a
// run is done ("Show draft"). Renders the section's best draft markdown with its reviewer
// verdict/score/feedback, revision count, and that draft's sources.
import type { ComponentPropsWithoutRef } from 'react'
import { Link, useParams } from 'react-router'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ArrowLeft } from 'lucide-react'
import { Badge, EmptyState, Skeleton } from '../components/ui'
import { SourceList } from '../components/report'
import { useRun } from '../api/queries'
import { linkifyCitations } from '../lib/citations'
import { MAX_REVISIONS_PER_SECTION } from '../lib/runView'
import type { Review } from '../types'

// Citation markers ([n] → #source-n) become superscript anchors into the SourceList, matching
// the ReportViewer; everything else stays a normal link (external opens in a new tab).
const mdComponents: Components = {
  a({ href, children, ...props }: ComponentPropsWithoutRef<'a'>) {
    if (href?.startsWith('#source-')) {
      return (
        <sup>
          <a href={href} {...props}>
            {children}
          </a>
        </sup>
      )
    }
    const external = href?.startsWith('http')
    return (
      <a href={href} {...(external ? { target: '_blank', rel: 'noreferrer' } : {})} {...props}>
        {children}
      </a>
    )
  },
}

function BackLink({ id }: { id: string }) {
  return (
    <Link
      to={`/runs/${id}`}
      className="inline-flex items-center gap-1.5 text-sm text-text-secondary outline-none transition-colors hover:text-text-primary focus-visible:ring-2 focus-visible:ring-accent"
    >
      <ArrowLeft size={14} />
      Back to run
    </Link>
  )
}

function ReviewMeta({ review, revision }: { review: Review | null; revision: number }) {
  return (
    <div className="mt-3 flex flex-wrap items-center gap-3 text-xs">
      {review ? (
        <>
          <Badge tone={review.verdict === 'approved' ? 'success' : 'warn'}>
            {review.verdict === 'approved' ? 'Approved' : 'Not approved'}
          </Badge>
          <span
            className={`font-mono ${review.verdict === 'approved' ? 'text-success' : 'text-warn'}`}
          >
            {review.score.toFixed(2)}
          </span>
        </>
      ) : (
        <span className="text-text-secondary">Not yet reviewed</span>
      )}
      <span className="font-mono text-text-secondary">
        rev {revision}/{MAX_REVISIONS_PER_SECTION}
      </span>
    </div>
  )
}

export function SectionDraftPage() {
  const { id, sectionId } = useParams<{ id: string; sectionId: string }>()
  const { data: detail, isLoading } = useRun(id ?? '')

  const section = detail?.plan.find((p) => p.id === sectionId)
  const draft = detail?.drafts.find((d) => d.section_id === sectionId)
  // Reviews accrue in wave order; the last one for this section is the latest verdict.
  const review = detail?.reviews.filter((r) => r.section_id === sectionId).at(-1) ?? null
  const revision = detail?.revision_counts?.[sectionId ?? ''] ?? draft?.revision ?? 0

  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      <div className="mb-6">
        <BackLink id={id ?? ''} />
        {isLoading ? (
          <Skeleton className="mt-3 h-6 w-64" />
        ) : (
          <>
            <h1 className="mt-3 text-xl font-semibold tracking-tight text-text-primary">
              {section?.title ?? 'Section draft'}
            </h1>
            {section?.objective && (
              <p className="mt-1 text-sm text-text-secondary">{section.objective}</p>
            )}
            {draft && <ReviewMeta review={review} revision={revision} />}
            {review?.verdict === 'revise' && review.feedback && (
              <p className="mt-3 rounded-control border border-warn/40 bg-warn/10 px-3 py-2 text-xs text-warn">
                {review.feedback}
              </p>
            )}
          </>
        )}
      </div>

      {isLoading ? (
        <div className="space-y-3">
          {[0, 1, 2, 3, 4].map((k) => (
            <Skeleton key={k} className="h-4 w-full" />
          ))}
        </div>
      ) : draft ? (
        <div className="rounded-card border border-border bg-surface px-5 py-5">
          <div className="prose-atlas max-w-[68ch]">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
              {linkifyCitations(draft.content_md)}
            </ReactMarkdown>
          </div>
          <div className="mt-8 border-t border-border pt-5">
            <h2 className="mb-3 text-sm font-semibold text-text-primary">Sources</h2>
            <SourceList sources={draft.sources} />
          </div>
        </div>
      ) : (
        <EmptyState
          title="No draft yet"
          description="This section hasn't produced a draft. Head back to the run to watch its progress."
          action={<BackLink id={id ?? ''} />}
        />
      )}
    </div>
  )
}
