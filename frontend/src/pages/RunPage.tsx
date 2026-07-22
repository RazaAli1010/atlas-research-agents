import { useParams } from 'react-router'
import { Loader2 } from 'lucide-react'
import { Badge, Card, Skeleton } from '../components/ui'
import { useRun } from '../api/queries'
import { useRunEvents } from '../api/useRunEvents'
import type { ConnectionState } from '../stores/runStore'

const CONNECTION_LABEL: Record<ConnectionState, string> = {
  connecting: 'connecting…',
  open: 'live',
  reconnecting: 'reconnecting…',
  closed: 'closed',
}

function ConnectionIndicator({ state }: { state: ConnectionState }) {
  const busy = state === 'connecting' || state === 'reconnecting'
  const dot =
    state === 'open'
      ? 'bg-success'
      : state === 'closed'
        ? 'bg-text-secondary'
        : 'bg-warn'
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-text-secondary">
      {busy ? (
        <Loader2 size={12} className="animate-spin text-warn" />
      ) : (
        <span className={`h-2 w-2 rounded-full ${dot}`} />
      )}
      {CONNECTION_LABEL[state]}
    </span>
  )
}

export function RunPage() {
  const { id } = useParams<{ id: string }>()
  const { data } = useRun(id ?? '')
  const { latestStatus, connectionState, events } = useRunEvents(id)

  const status = latestStatus ?? data?.status ?? null

  return (
    <div className="mx-auto max-w-4xl px-6 py-10">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          {data?.topic ? (
            <h1 className="truncate text-xl font-semibold tracking-tight text-text-primary">
              {data.topic}
            </h1>
          ) : (
            <h1 className="truncate font-mono text-sm text-text-secondary">{id}</h1>
          )}
          <div className="mt-2 flex items-center gap-3">
            {status && <Badge status={status} />}
            <ConnectionIndicator state={connectionState} />
            <span className="font-mono text-xs text-text-secondary">
              {events.length} events
            </span>
          </div>
        </div>
      </div>

      {/* Timeline / report land in F11 & F12 — placeholder skeleton for now. */}
      <Card className="mt-8">
        <div className="space-y-3">
          <Skeleton className="h-4 w-1/3" />
          <Skeleton className="h-4 w-2/3" />
          <Skeleton className="h-4 w-1/2" />
        </div>
      </Card>
    </div>
  )
}
