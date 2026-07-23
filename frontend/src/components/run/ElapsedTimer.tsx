// Elapsed run timer (F11). Ticks from created_at while the run is live; freezes when the
// run reaches a terminal state *while being watched*. For a run that is already terminal on
// mount (late-join) we can't know its true duration — RunDetail carries no finished_at — so
// the timer renders nothing rather than a bogus days-long elapsed.
import { useEffect, useState } from 'react'
import { Clock } from 'lucide-react'

function fmt(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000))
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${m}:${s.toString().padStart(2, '0')}`
}

export interface ElapsedTimerProps {
  createdAt?: string
  running: boolean
}

export function ElapsedTimer({ createdAt, running }: ElapsedTimerProps) {
  const start = createdAt ? new Date(createdAt).getTime() : NaN
  const [elapsed, setElapsed] = useState<number | null>(null)
  const [frozen, setFrozen] = useState<number | null>(null)

  useEffect(() => {
    if (Number.isNaN(start) || !running) return
    const tick = () => setElapsed(Date.now() - start)
    tick()
    const id = setInterval(tick, 1000)
    // Freeze on stop/unmount: cleanup fires exactly when `running` flips false, so the
    // last live value is preserved instead of recomputing a bogus elapsed on late-join.
    return () => {
      clearInterval(id)
      setFrozen(Date.now() - start)
    }
  }, [start, running])

  const value = running ? elapsed : frozen
  if (value === null || Number.isNaN(start)) return null

  return (
    <span className="inline-flex items-center gap-1.5 font-mono text-xs text-text-secondary">
      <Clock size={12} />
      {fmt(value)}
    </span>
  )
}
