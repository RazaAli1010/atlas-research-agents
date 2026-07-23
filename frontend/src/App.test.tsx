import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { api } from './api/client'

function renderApp(path = '/') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('App shell', () => {
  afterEach(() => vi.restoreAllMocks())

  it('renders the Atlas wordmark and sidebar nav', () => {
    renderApp('/')
    expect(screen.getByText('Atlas')).toBeInTheDocument()
    expect(screen.getAllByText('New Run').length).toBeGreaterThan(0)
    expect(screen.getByText('History')).toBeInTheDocument()
  })

  it('routes /history to the runs list (empty state when there are none)', async () => {
    vi.spyOn(api, 'listRuns').mockResolvedValue([])
    renderApp('/history')
    expect(await screen.findByText('No runs yet')).toBeInTheDocument()
  })
})
