// SSE connection indicator (F11). Never blanks the page — a dropped socket shows an amber
// "reconnecting" pill while useRunEvents retries with backoff.
import { cn } from '../../lib/cn'
import type { ConnectionState } from '../../stores/runStore'

const LABEL: Record<ConnectionState, string> = {
  connecting: 'connecting',
  open: 'live',
  reconnecting: 'reconnecting',
  closed: 'closed',
}

export function ConnectionPill({ state }: { state: ConnectionState }) {
  const busy = state === 'connecting' || state === 'reconnecting'
  const dot =
    state === 'open' ? 'bg-success' : state === 'closed' ? 'bg-text-secondary' : 'bg-warn'
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs',
        busy ? 'bg-warn/10 text-warn' : 'text-text-secondary',
      )}
      role="status"
    >
      <span className={cn('h-2 w-2 rounded-full', dot, busy && 'atlas-pulse')} />
      {LABEL[state]}
    </span>
  )
}
