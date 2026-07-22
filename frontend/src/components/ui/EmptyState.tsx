import type { ReactNode } from 'react'
import { cn } from '../../lib/cn'

export interface EmptyStateProps {
  title: string
  description?: ReactNode
  action?: ReactNode
  className?: string
}

// Illustration-free empty state (§8): text + one action.
export function EmptyState({ title, description, action, className }: EmptyStateProps) {
  return (
    <div className={cn('mx-auto max-w-sm text-center', className)}>
      <h2 className="text-base font-medium text-text-primary">{title}</h2>
      {description && (
        <p className="mt-2 text-sm leading-relaxed text-text-secondary">{description}</p>
      )}
      {action && <div className="mt-5 flex justify-center">{action}</div>}
    </div>
  )
}
