import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { RunPage } from './RunPage'
import { api } from '../api/client'
import { useRunStore } from '../stores/runStore'
import { FakeEventSource, installFakeEventSource } from '../test/fakeEventSource'
import type { AtlasEvent, RunDetail } from '../types'

function detail(overrides: Partial<RunDetail> = {}): RunDetail {
  return {
    run_id: 'r1',
    thread_id: 't1',
    topic: 'Compare vector DBs',
    status: 'done',
    created_at: '2026-07-23T12:00:00Z',
    cost_usd: 0.05,
    plan: [
      { id: 's1', title: 'Pricing tiers', objective: 'o', suggested_queries: [] },
      { id: 's2', title: 'Scale limits', objective: 'o', suggested_queries: [] },
    ],
    plan_approved: true,
    drafts: [
      { section_id: 's1', content_md: 'body', revision: 0, sources: [] },
      { section_id: 's2', content_md: 'body', revision: 0, sources: [] },
    ],
    reviews: [],
    revision_counts: {},
    final_report_md: '# Vector Database Pricing\n\nBody.',
    usage_log: [],
    cost_breakdown: { planner: 0.05 },
    trace_id: null,
    ...overrides,
  }
}

function renderRunPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/runs/r1']}>
        <Routes>
          <Route path="/runs/:id" element={<RunPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function emit(events: AtlasEvent[]) {
  const src = FakeEventSource.last()
  act(() => src.open())
  act(() => {
    for (const ev of events) src.emit(ev.type, ev)
  })
}

describe('RunPage', () => {
  beforeEach(() => {
    installFakeEventSource()
    useRunStore.setState({ byRun: {} })
  })
  afterEach(() => vi.restoreAllMocks())

  it('reconstructs a finished run from SSE replay (late-join)', async () => {
    vi.spyOn(api, 'getRun').mockResolvedValue(detail())
    const { container } = renderRunPage()
    await screen.findByText('Compare vector DBs')

    emit([
      { type: 'review', review: { section_id: 's1', verdict: 'approved', score: 0.9, feedback: '' } },
      { type: 'review', review: { section_id: 's2', verdict: 'approved', score: 0.9, feedback: '' } },
      { type: 'done', report_md: '# Vector Database Pricing\n\nBody.' },
    ])

    // Report rendered as markdown, sections reconstructed as approved, no skeletons left.
    expect(await screen.findByRole('heading', { name: 'Vector Database Pricing' })).toBeInTheDocument()
    expect(screen.getAllByText('Approved')).toHaveLength(2)
    await waitFor(() => expect(container.querySelector('.animate-pulse')).toBeNull())
  })

  it('shows a disabled approval placeholder while awaiting approval', async () => {
    vi.spyOn(api, 'getRun').mockResolvedValue(detail({ status: 'awaiting_approval' }))
    renderRunPage()
    await screen.findByText('Compare vector DBs')

    emit([
      { type: 'status', status: 'awaiting_approval' },
      {
        type: 'interrupt',
        payload: {
          plan: [{ id: 's1', title: 'Pricing tiers', objective: 'o', suggested_queries: [] }],
        },
      },
    ])

    const approve = await screen.findByRole('button', { name: /approve plan/i })
    expect(approve).toBeDisabled()
  })

  it('deep-links the LangSmith trace on error when trace_id is present', async () => {
    vi.stubEnv('VITE_LANGSMITH_BASE_URL', 'https://smith.langchain.com/o/o1/projects/p/p1')
    vi.spyOn(api, 'getRun').mockResolvedValue(detail({ status: 'failed', trace_id: 'abc' }))
    renderRunPage()
    await screen.findByText('Compare vector DBs')

    emit([{ type: 'error', message: 'Run cost ceiling exceeded' }])

    const link = await screen.findByRole('link', { name: /view trace in langsmith/i })
    expect(link).toHaveAttribute('href', 'https://smith.langchain.com/o/o1/projects/p/p1/r/abc')
    vi.unstubAllEnvs()
  })

  it('falls back to a static LangSmith link when trace_id is null (never a dead link)', async () => {
    vi.stubEnv('VITE_LANGSMITH_BASE_URL', 'https://smith.langchain.com/o/o1/projects/p/p1')
    vi.spyOn(api, 'getRun').mockResolvedValue(detail({ status: 'failed', trace_id: null }))
    renderRunPage()
    await screen.findByText('Compare vector DBs')

    emit([{ type: 'error', message: 'boom' }])

    const link = await screen.findByRole('link', { name: /view trace in langsmith/i })
    expect(link.getAttribute('href')).not.toBe('#')
    expect(link).toHaveAttribute('href', 'https://smith.langchain.com')
    vi.unstubAllEnvs()
  })
})
