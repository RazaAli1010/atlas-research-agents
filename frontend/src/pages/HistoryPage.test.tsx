import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { HistoryPage } from './HistoryPage'
import { api } from '../api/client'
import type { RunSummary } from '../types'

function renderHistory() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/history']}>
        <Routes>
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/runs/:id" element={<div>Run page opened</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const RUNS: RunSummary[] = [
  {
    run_id: 'r1',
    topic: 'Vector DB pricing',
    status: 'done',
    created_at: '2026-07-23T11:58:00Z',
    cost_usd: 0.1234,
  },
  {
    run_id: 'r2',
    topic: 'On-device LLMs',
    status: 'failed',
    created_at: '2026-07-23T10:00:00Z',
    cost_usd: 0.02,
  },
]

describe('HistoryPage', () => {
  afterEach(() => vi.restoreAllMocks())

  it('renders a row per run with status badge and monospace cost', async () => {
    vi.spyOn(api, 'listRuns').mockResolvedValue(RUNS)
    renderHistory()

    expect(await screen.findByText('Vector DB pricing')).toBeInTheDocument()
    expect(screen.getByText('On-device LLMs')).toBeInTheDocument()
    expect(screen.getByText('$0.1234')).toBeInTheDocument()
    expect(screen.getByText('Done')).toBeInTheDocument()
    expect(screen.getByText('Failed')).toBeInTheDocument()
  })

  it('navigates to the run on row click', async () => {
    vi.spyOn(api, 'listRuns').mockResolvedValue(RUNS)
    renderHistory()
    await userEvent.click(await screen.findByText('Vector DB pricing'))
    expect(await screen.findByText('Run page opened')).toBeInTheDocument()
  })

  it('shows an empty state when there are no runs', async () => {
    vi.spyOn(api, 'listRuns').mockResolvedValue([])
    renderHistory()
    await waitFor(() => expect(screen.getByText('No runs yet')).toBeInTheDocument())
  })
})
