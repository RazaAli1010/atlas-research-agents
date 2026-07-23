import { useMemo } from 'react'
import { Link, useParams } from 'react-router'
import { AlertTriangle, ArrowRight, ExternalLink, FileText } from 'lucide-react'
import { Badge, Card, Skeleton } from '../components/ui'
import {
  ConnectionPill,
  CostMeter,
  ElapsedTimer,
  NodeTimeline,
  ReportPane,
  SectionCard,
} from '../components/run'
import { PlanApprovalPanel } from '../components/approval'
import { useRun } from '../api/queries'
import { useRunEvents } from '../api/useRunEvents'
import { deriveRunView } from '../lib/runView'
import { reportPreview } from '../lib/reportPreview'
import { LANGSMITH_HOME, langsmithTraceUrl } from '../lib/langsmith'
import type { RunStatus } from '../types'

const TERMINAL: ReadonlySet<RunStatus> = new Set<RunStatus>(['done', 'failed'])

function ErrorBanner({ message, traceId }: { message: string; traceId: string | null }) {
  const deepLink = langsmithTraceUrl(traceId)
  return (
    <div className="flex items-start gap-3 rounded-card border border-danger/40 bg-danger/10 px-4 py-3">
      <AlertTriangle size={16} className="mt-0.5 shrink-0 text-danger" />
      <div className="min-w-0 text-sm">
        <p className="text-danger">{message}</p>
        <a
          href={deepLink ?? LANGSMITH_HOME}
          target="_blank"
          rel="noreferrer"
          className="mt-1 inline-flex items-center gap-1 text-xs text-text-secondary underline-offset-2 hover:text-text-primary hover:underline focus-visible:ring-2 focus-visible:ring-accent"
        >
          View trace in LangSmith
          <ExternalLink size={12} />
        </a>
      </div>
    </div>
  )
}

export function RunPage() {
  const { id } = useParams<{ id: string }>()
  const { data: detail } = useRun(id ?? '')
  const { events, interruptPayload, connectionState } = useRunEvents(id)

  // Prefer whichever source actually holds sections. `detail.plan` is a *truthy* empty [] for
  // an un-approved run (the plan lives only in the interrupt payload until it's approved), so
  // `??` would wrongly stop at it — pick the first non-empty array instead.
  const interruptPlan = interruptPayload?.plan
  const plan = useMemo(
    () => (interruptPlan?.length ? interruptPlan : (detail?.plan ?? [])),
    [detail?.plan, interruptPlan],
  )
  const view = useMemo(
    () => deriveRunView(events, plan, detail?.drafts),
    [events, plan, detail?.drafts],
  )

  const status = view.status ?? detail?.status ?? null
  const running = status !== null && !TERMINAL.has(status)
  const hasStarted = events.length > 0 || detail !== undefined

  // Live cost comes from the event stream; fall back to the hydrated snapshot before the
  // first usage event arrives (e.g. reconnecting to a finished run pre-replay).
  const costTotal = view.costTotal > 0 ? view.costTotal : (detail?.cost_usd ?? 0)
  const costByNode =
    Object.keys(view.costByNode).length > 0 ? view.costByNode : (detail?.cost_breakdown ?? {})

  const contentBySection = new Map(detail?.drafts?.map((d) => [d.section_id, d.content_md]))
  const reportMd = view.reportMd ?? (detail?.final_report_md ? detail.final_report_md : null)

  const awaitingApproval = status === 'awaiting_approval'

  const timelineCard = (
    <Card header="Progress">
      {hasStarted ? (
        <NodeTimeline view={view} />
      ) : (
        <div className="space-y-3">
          {[0, 1, 2, 3, 4].map((k) => (
            <Skeleton key={k} className="h-4 w-3/4" />
          ))}
        </div>
      )}
    </Card>
  )

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      {/* Header */}
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          {detail?.topic ? (
            <h1 className="truncate text-xl font-semibold tracking-tight text-text-primary">
              {detail.topic}
            </h1>
          ) : (
            <Skeleton className="h-6 w-64" />
          )}
          <div className="mt-2 flex items-center gap-3">
            {status && <Badge status={status} />}
            <ConnectionPill state={connectionState} />
            <ElapsedTimer createdAt={detail?.created_at} running={running} />
          </div>
        </div>
        <CostMeter costTotal={costTotal} costByNode={costByNode} />
      </header>

      {view.errorMessage && (
        <div className="mt-6">
          <ErrorBanner message={view.errorMessage} traceId={detail?.trace_id ?? null} />
        </div>
      )}

      {awaitingApproval ? (
        /* Approval: full-width plan with the progress timeline stacked above it. */
        <div className="mt-8 space-y-6">
          {timelineCard}
          <PlanApprovalPanel key={id} runId={id ?? ''} proposedPlan={plan} />
        </div>
      ) : (
        /* Body: narrow timeline rail + wide main column (rail collapses under 1100px). */
        <div className="mt-8 grid gap-6 min-[1100px]:grid-cols-[260px_1fr]">
          <aside>{timelineCard}</aside>

          <main className="space-y-6">
            {view.sections.length > 0 ? (
              <div className="grid gap-4 sm:grid-cols-2">
                {view.sections.map((s) => (
                  <SectionCard
                    key={s.id}
                    section={s}
                    runId={id ?? ''}
                    contentMd={contentBySection.get(s.id)}
                  />
                ))}
              </div>
            ) : (
              !hasStarted && (
                <div className="grid gap-4 sm:grid-cols-2">
                  <Skeleton className="h-28 w-full" />
                  <Skeleton className="h-28 w-full" />
                </div>
              )
            )}

            {reportMd !== null ? (
              <Card header="Report ready">
                <div className="flex items-start gap-3">
                  <span className="mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-control bg-accent/15 text-accent">
                    <FileText size={18} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="line-clamp-3 text-sm text-text-secondary">
                      {reportPreview(reportMd)}
                    </p>
                    <div className="mt-3 flex items-center gap-4">
                      <Link
                        to={`/runs/${id}/report`}
                        className="inline-flex items-center gap-1.5 rounded-control bg-accent px-3 py-1.5 text-sm font-medium text-background outline-none transition-colors hover:bg-accent/90 focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-surface focus-visible:ring-accent"
                      >
                        Open full report
                        <ArrowRight size={14} />
                      </Link>
                      <span className="font-mono text-xs text-text-secondary">
                        {(detail?.sources?.length ?? 0)} sources
                      </span>
                    </div>
                  </div>
                </div>
              </Card>
            ) : (
              <Card header="Report">
                <ReportPane writerDraft={view.writerDraft} reportMd={null} />
              </Card>
            )}
          </main>
        </div>
      )}
    </div>
  )
}
