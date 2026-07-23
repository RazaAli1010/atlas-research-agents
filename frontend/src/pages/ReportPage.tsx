// Dedicated, distraction-free report page. The run page shows a compact "Report ready" card
// that links here; this route renders the full formatted report (ReportViewer) on its own.
import { Link, useParams } from 'react-router'
import { ArrowLeft } from 'lucide-react'
import { EmptyState, Skeleton } from '../components/ui'
import { ReportViewer } from '../components/report'
import { useRun } from '../api/queries'

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

export function ReportPage() {
  const { id } = useParams<{ id: string }>()
  const { data: detail, isLoading } = useRun(id ?? '')

  const reportMd = detail?.final_report_md ?? ''
  const hasReport = reportMd.trim().length > 0

  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      <div className="mb-6">
        <BackLink id={id ?? ''} />
        {detail?.topic ? (
          <h1 className="mt-3 text-xl font-semibold tracking-tight text-text-primary">
            {detail.topic}
          </h1>
        ) : (
          <Skeleton className="mt-3 h-6 w-64" />
        )}
      </div>

      {isLoading ? (
        <div className="space-y-3">
          {[0, 1, 2, 3, 4].map((k) => (
            <Skeleton key={k} className="h-4 w-full" />
          ))}
        </div>
      ) : hasReport ? (
        <ReportViewer
          reportMd={reportMd}
          sources={detail?.sources ?? []}
          runId={id ?? ''}
          traceId={detail?.trace_id ?? null}
        />
      ) : (
        <EmptyState
          title="No report yet"
          description="This run hasn't finished writing its report. Head back to the run to watch its progress."
          action={<BackLink id={id ?? ''} />}
        />
      )}
    </div>
  )
}
