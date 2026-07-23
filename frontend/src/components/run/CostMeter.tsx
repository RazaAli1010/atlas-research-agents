// Running cost readout (F11): monospace total + a thin bar vs the run ceiling, warn past
// 80%, with a per-node hover breakdown (cost_breakdown shape from F9).
import { Tooltip } from '../ui'
import { cn } from '../../lib/cn'

// Mirrors backend RUN_COST_CEILING_USD in backend/app/graph/state.py.
export const RUN_COST_CEILING_USD = 1.5
const WARN_FRACTION = 0.8

export interface CostMeterProps {
  costTotal: number
  costByNode: Record<string, number>
}

export function CostMeter({ costTotal, costByNode }: CostMeterProps) {
  const fraction = Math.min(costTotal / RUN_COST_CEILING_USD, 1)
  const warn = costTotal >= RUN_COST_CEILING_USD * WARN_FRACTION
  const nodes = Object.entries(costByNode).sort((a, b) => b[1] - a[1])

  const breakdown = (
    <div className="min-w-32 space-y-0.5">
      {nodes.length === 0 ? (
        <div className="text-text-secondary">No cost yet</div>
      ) : (
        nodes.map(([node, cost]) => (
          <div key={node} className="flex justify-between gap-4">
            <span className="text-text-secondary">{node}</span>
            <span className="font-mono">${cost.toFixed(4)}</span>
          </div>
        ))
      )}
    </div>
  )

  return (
    <Tooltip label={breakdown}>
      <div className="flex items-center gap-2">
        <span className={cn('font-mono text-sm', warn ? 'text-warn' : 'text-text-primary')}>
          ${costTotal.toFixed(4)}
        </span>
        <span className="h-1.5 w-16 overflow-hidden rounded-full bg-raised" aria-hidden>
          <span
            className={cn('block h-full rounded-full', warn ? 'bg-warn' : 'bg-accent')}
            style={{ width: `${fraction * 100}%` }}
          />
        </span>
      </div>
    </Tooltip>
  )
}
