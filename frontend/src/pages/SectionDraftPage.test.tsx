import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SectionDraftPage } from './SectionDraftPage'
import { api } from '../api/client'
import type { RunDetail } from '../types'

function detail(overrides: Partial<RunDetail> = {}): RunDetail {
  return {
    run_id: 'r1',
    thread_id: 't1',
    topic: 'Compare vector DBs',
    status: 'done',
    created_at: '2026-07-23T12:00:00Z',
    cost_usd: 0.05,
    plan: [{ id: 's1', title: 'Pricing tiers', objective: 'Compare costs', suggested_queries: [] }],
    plan_approved: true,
    drafts: [
      {
        section_id: 's1',
        content_md: 'Pinecone is cheapest [1].',
        revision: 2,
        sources: [{ url: 'https://pinecone.io', title: 'Pinecone', snippet: 's', tool: 'web_search' }],
      },
    ],
    reviews: [
      { section_id: 's1', verdict: 'revise', score: 0.6, feedback: 'Add a cost table.' },
    ],
    revision_counts: { s1: 2 },
    final_report_md: '',
    usage_log: [],
    cost_breakdown: {},
    trace_id: null,
    sources: [],
    ...overrides,
  }
}

function renderDraftPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/runs/r1/sections/s1']}>
        <Routes>
          <Route path="/runs/:id/sections/:sectionId" element={<SectionDraftPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('SectionDraftPage', () => {
  afterEach(() => vi.restoreAllMocks())

  it('renders the draft with reviewer verdict, feedback, and sources', async () => {
    vi.spyOn(api, 'getRun').mockResolvedValue(detail())
    renderDraftPage()

    expect(await screen.findByRole('heading', { name: 'Pricing tiers' })).toBeInTheDocument()
    expect(screen.getByText('Not approved')).toBeInTheDocument()
    expect(screen.getByText('0.60')).toBeInTheDocument()
    expect(screen.getByText('rev 2/2')).toBeInTheDocument()
    expect(screen.getByText('Add a cost table.')).toBeInTheDocument()
    // Citation superscript anchored to the draft's source list.
    const citation = await screen.findByRole('link', { name: '1' })
    expect(citation).toHaveAttribute('href', '#source-1')
    expect(document.getElementById('source-1')).not.toBeNull()
  })

  it('shows an empty state when the section has no draft', async () => {
    vi.spyOn(api, 'getRun').mockResolvedValue(detail({ drafts: [] }))
    renderDraftPage()

    expect(await screen.findByText(/no draft yet/i)).toBeInTheDocument()
  })
})
