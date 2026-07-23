import { useMemo } from 'react'
import { useParams } from 'react-router'
import { AlertTriangle, ExternalLink } from 'lucide-react'
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
import { ReportViewer } from '../components/report'
import { useRun } from '../api/queries'
import { useRunEvents } from '../api/useRunEvents'
import { deriveRunView } from '../lib/runView'
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

  const plan = useMemo(
    () => detail?.plan ?? interruptPayload?.plan ?? [],
    [detail?.plan, interruptPayload?.plan],
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

      {/* Body: timeline rail + main column (rail collapses under 1100px). */}
      <div className="mt-8 grid gap-6 min-[1100px]:grid-cols-[260px_1fr]">
        <aside className="min-[1100px]:order-1">
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
        </aside>

        <main className="space-y-6">
          {status === 'awaiting_approval' && (
            <PlanApprovalPanel
              key={id}
              runId={id ?? ''}
              proposedPlan={interruptPayload?.plan ?? detail?.plan ?? []}
            />
          )}

          {view.sections.length > 0 ? (
            <div className="grid gap-4 sm:grid-cols-2">
              {view.sections.map((s) => (
                <SectionCard key={s.id} section={s} contentMd={contentBySection.get(s.id)} />
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
            <ReportViewer
              reportMd={reportMd}
              sources={detail?.sources ?? []}
              runId={id ?? ''}
              traceId={detail?.trace_id ?? null}
            />
          ) : (
            <Card header="Report">
              <ReportPane writerDraft={view.writerDraft} reportMd={null} />
            </Card>
          )}
        </main>
      </div>
    </div>
  )
}
