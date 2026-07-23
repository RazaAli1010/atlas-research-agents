// LangSmith trace deep-link (F11). Built from VITE_LANGSMITH_BASE_URL (same import.meta.env
// pattern as client.ts) + the run's trace_id. Returns null when either is missing so callers
// render a static fallback link, never a dead `#`.

// Fallback when we can't build a run-specific deep-link (no base configured / untraced run).
export const LANGSMITH_HOME = 'https://smith.langchain.com'

export function langsmithTraceUrl(traceId: string | null): string | null {
  // Read env per-call (not module-load) so it stays overridable in tests.
  const base = (import.meta.env.VITE_LANGSMITH_BASE_URL ?? '').replace(/\/$/, '')
  if (!base || !traceId) return null
  return `${base}/r/${traceId}`
}
