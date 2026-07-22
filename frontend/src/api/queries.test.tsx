import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { runKeys, useCreateRun, useResumeRun } from './queries'
import { api } from './client'

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const spy = vi.spyOn(qc, 'invalidateQueries').mockResolvedValue()
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  )
  return { wrapper, spy }
}

describe('query invalidation', () => {
  afterEach(() => vi.restoreAllMocks())

  it('useCreateRun invalidates runKeys.all on success', async () => {
    vi.spyOn(api, 'createRun').mockResolvedValue({ run_id: 'r1', thread_id: 't1' })
    const { wrapper, spy } = makeWrapper()
    const { result } = renderHook(() => useCreateRun(), { wrapper })

    await result.current.mutateAsync('topic')
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith({ queryKey: runKeys.all }),
    )
  })

  it('useResumeRun invalidates detail(id) + all on success', async () => {
    vi.spyOn(api, 'resumeRun').mockResolvedValue()
    const { wrapper, spy } = makeWrapper()
    const { result } = renderHook(() => useResumeRun('r1'), { wrapper })

    await result.current.mutateAsync({ action: 'approve' })
    await waitFor(() => {
      expect(spy).toHaveBeenCalledWith({ queryKey: runKeys.detail('r1') })
      expect(spy).toHaveBeenCalledWith({ queryKey: runKeys.all })
    })
  })
})
