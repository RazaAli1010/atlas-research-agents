// Reconnecting SSE hook. Feeds the single per-run stream in `runStore`; many components
// read the same slice via selector. Handles F6's named-event frames + full-replay-on-reconnect.
import { useEffect } from 'react'
import { useShallow } from 'zustand/react/shallow'
import {
  ATLAS_EVENT_TYPES,
  type RunStatus,
  type SectionPlan,
} from '../types'
import {
  EMPTY_RUN_STREAM,
  useRunStore,
  type ConnectionState,
  type RunStreamState,
} from '../stores/runStore'
import { api } from './client'

export type RunEvents = RunStreamState

const TERMINAL = new Set(['done', 'error'])
const MAX_BACKOFF_MS = 15000

export function useRunEvents(runId: string | undefined): RunEvents {
  const { reset, ingest, setConnectionState } = useRunStore(
    useShallow((s) => ({
      reset: s.reset,
      ingest: s.ingest,
      setConnectionState: s.setConnectionState,
    })),
  )

  useEffect(() => {
    if (!runId) return

    let es: EventSource | null = null
    let attempt = 0
    let timer: ReturnType<typeof setTimeout> | null = null
    let terminated = false
    let disposed = false

    const clearTimer = () => {
      if (timer !== null) {
        clearTimeout(timer)
        timer = null
      }
    }

    const connect = () => {
      if (disposed) return
      reset(runId) // each fresh socket is a full-state rebuild (F6 replays history)
      setConnectionState(runId, attempt === 0 ? 'connecting' : 'reconnecting')
      const ES = globalThis.EventSource
      es = new ES(api.eventsUrl(runId))

      es.onopen = () => {
        attempt = 0
        setConnectionState(runId, 'open')
      }

      for (const type of ATLAS_EVENT_TYPES) {
        es.addEventListener(type, (e) => {
          let parsed: unknown
          try {
            parsed = JSON.parse((e as MessageEvent).data)
          } catch {
            return // drop malformed frame; keep the socket alive
          }
          ingest(runId, parsed as never)
          if (TERMINAL.has(type)) {
            terminated = true
            clearTimer()
            es?.close()
            setConnectionState(runId, 'closed')
          }
        })
      }

      es.onerror = () => {
        if (disposed || terminated) return
        es?.close()
        setConnectionState(runId, 'reconnecting')
        const delay = Math.min(1000 * 2 ** attempt, MAX_BACKOFF_MS)
        attempt += 1
        clearTimer()
        timer = setTimeout(connect, delay)
      }
    }

    connect()

    return () => {
      disposed = true
      clearTimer()
      es?.close()
    }
  }, [runId, reset, ingest, setConnectionState])

  return useRunStore(
    useShallow((s) => (runId ? s.byRun[runId] ?? EMPTY_RUN_STREAM : EMPTY_RUN_STREAM)),
  )
}

// Re-exported for consumers that only need the derived types.
export type { ConnectionState, RunStatus, SectionPlan }
