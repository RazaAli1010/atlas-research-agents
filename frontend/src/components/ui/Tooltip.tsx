import { useId, useState, type ReactNode } from 'react'
import { cn } from '../../lib/cn'

export interface TooltipProps {
  label: ReactNode
  children: ReactNode
  className?: string
}

// Hover/focus tooltip — pure CSS/JS, no portal library. Linked via aria-describedby.
export function Tooltip({ label, children, className }: TooltipProps) {
  const [open, setOpen] = useState(false)
  const id = useId()
  return (
    <span
      className={cn('relative inline-flex', className)}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
      aria-describedby={open ? id : undefined}
    >
      {children}
      {open && (
        <span
          role="tooltip"
          id={id}
          className="pointer-events-none absolute bottom-full left-1/2 z-10 mb-1.5 -translate-x-1/2 whitespace-nowrap rounded-control border border-border bg-raised px-2 py-1 text-xs text-text-primary shadow-lg"
        >
          {label}
        </span>
      )}
    </span>
  )
}
