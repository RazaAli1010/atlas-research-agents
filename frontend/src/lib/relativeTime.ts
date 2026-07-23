// Relative + absolute timestamp helpers (§8: timestamps relative, absolute on hover).
// Pure given an explicit `now` (tests pass one; UI defaults to Date.now()).

const RTF = new Intl.RelativeTimeFormat('en', { numeric: 'auto' })

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ['year', 365 * 24 * 60 * 60 * 1000],
  ['month', 30 * 24 * 60 * 60 * 1000],
  ['day', 24 * 60 * 60 * 1000],
  ['hour', 60 * 60 * 1000],
  ['minute', 60 * 1000],
  ['second', 1000],
]

/** "2m ago", "just now", "in 3h" — from an ISO-8601 string. */
export function relativeTime(iso: string, now: number = Date.now()): string {
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ''
  const diff = then - now // negative = past
  const abs = Math.abs(diff)
  if (abs < 5000) return 'just now'
  for (const [unit, ms] of UNITS) {
    if (abs >= ms) return RTF.format(Math.round(diff / ms), unit)
  }
  return 'just now'
}

/** Full local timestamp for the hover tooltip. */
export function absoluteTime(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString()
}
