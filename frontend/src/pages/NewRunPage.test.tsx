import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { NewRunPage } from './NewRunPage'
import { api, ApiError } from '../api/client'

function wrapper(children: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={children} />
          <Route path="/runs/:id" element={<div>Run page for abc</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

describe('NewRunPage', () => {
  afterEach(() => vi.restoreAllMocks())

  it('Ctrl+Enter creates a run and navigates to /runs/:id', async () => {
    const createSpy = vi
      .spyOn(api, 'createRun')
      .mockResolvedValue({ run_id: 'abc', thread_id: 't' })
    const user = userEvent.setup()
    render(wrapper(<NewRunPage />))

    const textarea = screen.getByRole('textbox')
    await user.click(textarea)
    await user.keyboard('vector db pricing')
    await user.keyboard('{Control>}{Enter}{/Control}')

    await waitFor(() => expect(createSpy).toHaveBeenCalled())
    expect(createSpy.mock.calls[0][0]).toBe('vector db pricing')
    await screen.findByText(/Run page for/)
  })

  it('keeps submit disabled for empty/whitespace input', async () => {
    const user = userEvent.setup()
    render(wrapper(<NewRunPage />))
    const submit = screen.getByRole('button', { name: /start research/i })
    expect(submit).toBeDisabled()

    await user.click(screen.getByRole('textbox'))
    await user.keyboard('   ')
    expect(submit).toBeDisabled()
  })

  it('renders an ApiError inline', async () => {
    vi.spyOn(api, 'createRun').mockRejectedValue(new ApiError(500, 'server exploded'))
    const user = userEvent.setup()
    render(wrapper(<NewRunPage />))

    await user.click(screen.getByRole('textbox'))
    await user.keyboard('topic')
    await user.click(screen.getByRole('button', { name: /start research/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent('server exploded')
  })

  it('example chips fill the textarea', async () => {
    const user = userEvent.setup()
    render(wrapper(<NewRunPage />))
    await user.click(
      screen.getByRole('button', {
        name: /Compare vector database pricing for a seed-stage startup/i,
      }),
    )
    expect(screen.getByRole('textbox')).toHaveValue(
      'Compare vector database pricing for a seed-stage startup',
    )
  })
})
