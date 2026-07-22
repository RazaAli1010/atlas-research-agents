import type { HTMLAttributes, ReactNode } from 'react'
import { cn } from '../../lib/cn'

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  header?: ReactNode
  footer?: ReactNode
}

export function Card({ header, footer, className, children, ...props }: CardProps) {
  return (
    <div
      className={cn('rounded-card border border-border bg-surface', className)}
      {...props}
    >
      {header && (
        <div className="border-b border-border px-4 py-3 text-sm font-medium text-text-primary">
          {header}
        </div>
      )}
      <div className="px-4 py-3">{children}</div>
      {footer && (
        <div className="border-t border-border px-4 py-3 text-sm text-text-secondary">
          {footer}
        </div>
      )}
    </div>
  )
}
