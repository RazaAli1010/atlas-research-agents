import { act, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useRunEvents } from './useRunEvents'
import { useRunStore } from '../stores/runStore'
import { FakeEventSource, installFakeEventSource } from '../test/fakeEventSource'

function Probe({ runId }: { runId: string }) {
  const { events, latestStatus, totalCost, interruptPayload, reportMd, connectionState } =
    useRunEvents(runId)
  return (
    <div>
      <span data-testid="count">{events.length}</span>
      <span data-testid="status">{latestStatus ?? ''}</span>
      <span data-testid="cost">{totalCost}</span>
      <span data-testid="interrupt">{interruptPayload ? interruptPayload.plan.length : ''}</span>
      <span data-testid="report">{reportMd ?? ''}</span>
      <span data-testid="conn">{connectionState}</span>
    </div>
  )
}

const SAMPLES: [string, unknown][] = [
  ['status', { type: 'status', status: 'researching' }],
  ['node_started', { type: 'node_started', node: 'worker', section_id: 's1' }],
  ['usage', { type: 'usage', event: { node: 'planner', model: 'm', input_tokens: 1, output_tokens: 1, cost_usd: 0.01 }, total_cost_usd: 0.42 }],
  ['interrupt', { type: 'interrupt', payload: { plan: [{ id: 's1', title: 't', objective: 'o', suggested_queries: [] }] } }],
]

describe('useRunEvents reconnect', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    installFakeEventSource()
    useRunStore.setState({ byRun: {} })
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('folds events, reconnects on error, replays without duplication, stops on done', () => {
    const { getByTestId, unmount } = render(<Probe runId="r1" />)

    // Initial socket opens and folds the first wave.
    const first = FakeEventSource.last()
    act(() => first.open())
    expect(getByTestId('conn').textContent).toBe('open')

    act(() => {
      for (const [type, data] of SAMPLES) first.emit(type, data)
    })
    expect(getByTestId('count').textContent).toBe('4')
    expect(getByTestId('status').textContent).toBe('researching')
    expect(getByTestId('cost').textContent).toBe('0.42')
    expect(getByTestId('interrupt').textContent).toBe('1')

    // Non-terminal error → reconnecting, and a new socket after backoff.
    act(() => first.error())
    expect(getByTestId('conn').textContent).toBe('reconnecting')
    const before = FakeEventSource.instances.length
    act(() => {
      vi.advanceTimersByTime(1000)
    })
    expect(FakeEventSource.instances.length).toBe(before + 1)

    // New socket replays the full history (4) + one more; reset-on-reopen dedupes.
    const second = FakeEventSource.last()
    act(() => second.open())
    act(() => {
      for (const [type, data] of SAMPLES) second.emit(type, data)
      second.emit('node_finished', { type: 'node_finished', node: 'worker', summary: 'done s1' })
    })
    expect(getByTestId('count').textContent).toBe('5') // 4 replayed + 1, no duplicates

    // Terminal event closes and stops reconnecting.
    act(() => second.emit('done', { type: 'done', report_md: '# Report' }))
    expect(getByTestId('report').textContent).toBe('# Report')
    expect(getByTestId('status').textContent).toBe('done')
    expect(getByTestId('conn').textContent).toBe('closed')

    const afterDone = FakeEventSource.instances.length
    act(() => {
      vi.advanceTimersByTime(30000)
    })
    expect(FakeEventSource.instances.length).toBe(afterDone) // no further reconnect

    unmount()
  })
})
