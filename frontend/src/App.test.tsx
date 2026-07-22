import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import App from './App'

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
  it('renders the Atlas wordmark and sidebar nav', () => {
    renderApp('/')
    expect(screen.getByText('Atlas')).toBeInTheDocument()
    expect(screen.getAllByText('New Run').length).toBeGreaterThan(0)
    expect(screen.getByText('History')).toBeInTheDocument()
  })

  it('routes /history to the empty-state placeholder', () => {
    renderApp('/history')
    expect(screen.getByText('No runs yet')).toBeInTheDocument()
  })
})
