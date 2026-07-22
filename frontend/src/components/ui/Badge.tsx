import type { ReactNode } from 'react'
import type { RunStatus } from '../../types'
import { cn } from '../../lib/cn'

export type Tone = 'accent' | 'warn' | 'success' | 'danger' | 'neutral'

const TONE_CLASS: Record<Tone, string> = {
  accent: 'bg-accent/15 text-accent',
  warn: 'bg-warn/15 text-warn',
  success: 'bg-success/15 text-success',
  danger: 'bg-danger/15 text-danger',
  neutral: 'bg-raised text-text-secondary',
}

const STATUS_TONE: Record<RunStatus, Tone> = {
  planning: 'accent',
  researching: 'accent',
  reviewing: 'accent',
  writing: 'accent',
  awaiting_approval: 'warn',
  done: 'success',
  failed: 'danger',
}

const STATUS_LABEL: Record<RunStatus, string> = {
  planning: 'Planning',
  awaiting_approval: 'Awaiting approval',
  researching: 'Researching',
  reviewing: 'Reviewing',
  writing: 'Writing',
  done: 'Done',
  failed: 'Failed',
}

export interface BadgeProps {
  status?: RunStatus
  tone?: Tone
  children?: ReactNode
  className?: string
}

export function Badge({ status, tone, children, className }: BadgeProps) {
  const resolvedTone: Tone = tone ?? (status ? STATUS_TONE[status] : 'neutral')
  const label = children ?? (status ? STATUS_LABEL[status] : null)
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium',
        TONE_CLASS[resolvedTone],
        className,
      )}
    >
      {label}
    </span>
  )
}
