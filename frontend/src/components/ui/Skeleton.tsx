import { cn } from '../../lib/cn'

export interface SkeletonProps {
  className?: string
}

// Animated placeholder — never a spinner for page loads (§8). Size via className.
export function Skeleton({ className }: SkeletonProps) {
  return (
    <div
      className={cn('animate-pulse rounded-control bg-raised', className)}
      aria-hidden="true"
    />
  )
}
