import type { ReactNode } from 'react'
import { cn } from '../../lib/cn'

export interface KbdProps {
  children: ReactNode
  className?: string
}

// Monospace keycap for shortcut hints (⌘ / Ctrl, ↵).
export function Kbd({ children, className }: KbdProps) {
  return (
    <kbd
      className={cn(
        'inline-flex min-w-5 items-center justify-center rounded border border-border bg-raised px-1.5 py-0.5 font-mono text-xs text-text-secondary',
        className,
      )}
    >
      {children}
    </kbd>
  )
}
