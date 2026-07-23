import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ReportPage } from './ReportPage'
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
    plan: [],
    plan_approved: true,
    drafts: [],
    reviews: [],
    revision_counts: {},
    final_report_md:
      '# Vector Database Pricing\n\nPinecone leads [1].\n\n## Sources\n1. [Pinecone](https://pinecone.io)',
    usage_log: [],
    cost_breakdown: {},
    trace_id: null,
    sources: [{ url: 'https://pinecone.io', title: 'Pinecone', snippet: 's', tool: 'web_search' }],
    ...overrides,
  }
}

function renderReportPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/runs/r1/report']}>
        <Routes>
          <Route path="/runs/:id/report" element={<ReportPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ReportPage', () => {
  afterEach(() => vi.restoreAllMocks())

  it('renders the full report with clickable superscript citations', async () => {
    vi.spyOn(api, 'getRun').mockResolvedValue(detail())
    renderReportPage()

    expect(await screen.findByRole('heading', { name: 'Vector Database Pricing' })).toBeInTheDocument()
    const citation = await screen.findByRole('link', { name: '1' })
    expect(citation).toHaveAttribute('href', '#source-1')
    expect(citation.closest('sup')).not.toBeNull()
    // Structured source list rendered (not the raw markdown "## Sources" list).
    expect(document.getElementById('source-1')).not.toBeNull()
    // Back link to the run.
    expect(screen.getByRole('link', { name: /back to run/i })).toHaveAttribute('href', '/runs/r1')
  })

  it('shows an empty state when the run has no report yet', async () => {
    vi.spyOn(api, 'getRun').mockResolvedValue(detail({ status: 'researching', final_report_md: '' }))
    renderReportPage()

    expect(await screen.findByText(/no report yet/i)).toBeInTheDocument()
  })
})
