import { useNavigate } from 'react-router'
import { Check, Minus, Plus, X } from 'lucide-react'
import { Badge, Button, EmptyState, Skeleton, Tooltip } from '../components/ui'
import { useRuns } from '../api/queries'
import { absoluteTime, relativeTime } from '../lib/relativeTime'
import type { RunStatus, RunSummary } from '../types'

function SuccessGlyph({ status }: { status: RunStatus }) {
  if (status === 'done') return <Check size={16} className="text-success" aria-label="done" />
  if (status === 'failed') return <X size={16} className="text-danger" aria-label="failed" />
  return <Minus size={16} className="text-text-secondary" aria-label="in progress" />
}

function Row({ run, onOpen }: { run: RunSummary; onOpen: () => void }) {
  return (
    <tr
      onClick={onOpen}
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter') onOpen()
      }}
      className="cursor-pointer border-t border-border outline-none transition-colors hover:bg-raised/50 focus-visible:bg-raised/50"
    >
      <td className="max-w-0 truncate px-4 py-3 text-sm text-text-primary">{run.topic}</td>
      <td className="px-4 py-3">
        <Badge status={run.status} />
      </td>
      <td className="px-4 py-3 text-sm text-text-secondary">
        <Tooltip label={absoluteTime(run.created_at)}>
          <span>{relativeTime(run.created_at)}</span>
        </Tooltip>
      </td>
      <td className="px-4 py-3 text-right font-mono text-sm text-text-secondary">
        ${run.cost_usd.toFixed(4)}
      </td>
      <td className="px-4 py-3 text-center">
        <SuccessGlyph status={run.status} />
      </td>
    </tr>
  )
}

export function HistoryPage() {
  const navigate = useNavigate()
  const { data: runs, isPending } = useRuns()

  if (isPending) {
    return (
      <div className="mx-auto max-w-4xl px-6 py-10">
        <h1 className="text-xl font-semibold tracking-tight text-text-primary">History</h1>
        <div className="mt-6 space-y-2">
          {[0, 1, 2, 3].map((k) => (
            <Skeleton key={k} className="h-12 w-full" />
          ))}
        </div>
      </div>
    )
  }

  if (!runs || runs.length === 0) {
    return (
      <div className="mx-auto flex min-h-full max-w-4xl items-center justify-center px-6 py-16">
        <EmptyState
          title="No runs yet"
          description="Runs you start will appear here with their status and cost."
          action={
            <Button onClick={() => navigate('/')}>
              <Plus size={16} />
              New Run
            </Button>
          }
        />
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-4xl px-6 py-10">
      <h1 className="text-xl font-semibold tracking-tight text-text-primary">History</h1>
      <div className="mt-6 overflow-hidden rounded-card border border-border">
        <table className="w-full table-fixed">
          <thead>
            <tr className="bg-surface text-left text-xs uppercase tracking-wide text-text-secondary">
              <th className="px-4 py-2 font-medium">Topic</th>
              <th className="w-40 px-4 py-2 font-medium">Status</th>
              <th className="w-32 px-4 py-2 font-medium">Created</th>
              <th className="w-28 px-4 py-2 text-right font-medium">Cost</th>
              <th className="w-16 px-4 py-2 text-center font-medium">OK</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => (
              <Row key={run.run_id} run={run} onOpen={() => navigate(`/runs/${run.run_id}`)} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
