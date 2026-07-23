import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PlanApprovalPanel } from './PlanApprovalPanel'
import { api, ApiError } from '../../api/client'
import { runKeys } from '../../api/queries'
import type { SectionPlan } from '../../types'

function plan(n: number): SectionPlan[] {
  return Array.from({ length: n }, (_, i) => ({
    id: `s${i + 1}`,
    title: `Section ${i + 1}`,
    objective: `objective ${i + 1}`,
    suggested_queries: [],
  }))
}

function renderPanel(proposedPlan: SectionPlan[]) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const invalidate = vi.spyOn(qc, 'invalidateQueries')
  const user = userEvent.setup()
  render(
    <QueryClientProvider client={qc}>
      <PlanApprovalPanel runId="r1" proposedPlan={proposedPlan} />
    </QueryClientProvider>,
  )
  return { user, invalidate }
}

describe('PlanApprovalPanel', () => {
  afterEach(() => vi.restoreAllMocks())

  it('sends an edit payload with renumbered ids after rename + delete', async () => {
    const resume = vi.spyOn(api, 'resumeRun').mockResolvedValue(undefined)
    const { user } = renderPanel(plan(3))

    const title1 = screen.getByLabelText('Section 1 title')
    await user.clear(title1)
    await user.type(title1, 'Renamed one')
    await user.click(screen.getByRole('button', { name: 'Delete section 2' }))

    await user.click(screen.getByRole('button', { name: /approve with edits/i }))

    await waitFor(() => expect(resume).toHaveBeenCalledTimes(1))
    const [id, body] = resume.mock.calls[0]
    expect(id).toBe('r1')
    expect(body).toEqual({
      action: 'edit',
      plan: [
        { id: 's1', title: 'Renamed one', objective: 'objective 1', suggested_queries: [] },
        { id: 's2', title: 'Section 3', objective: 'objective 3', suggested_queries: [] },
      ],
    })
  })

  it('approves unedited with an approve payload (no plan)', async () => {
    const resume = vi.spyOn(api, 'resumeRun').mockResolvedValue(undefined)
    const { user } = renderPanel(plan(2))

    await user.click(screen.getByRole('button', { name: 'Approve plan' }))

    await waitFor(() => expect(resume).toHaveBeenCalledWith('r1', { action: 'approve' }))
  })

  it('discards edits and approves the original', async () => {
    const resume = vi.spyOn(api, 'resumeRun').mockResolvedValue(undefined)
    const { user } = renderPanel(plan(2))

    await user.type(screen.getByLabelText('Section 1 title'), ' edited')
    await user.click(screen.getByRole('button', { name: /discard edits & approve original/i }))

    await waitFor(() => expect(resume).toHaveBeenCalledWith('r1', { action: 'approve' }))
  })

  it('disables "Add section" at MAX_SECTIONS', () => {
    renderPanel(plan(6))
    expect(screen.getByRole('button', { name: /add section/i })).toBeDisabled()
  })

  it('enables "Add section" below the cap', () => {
    renderPanel(plan(5))
    expect(screen.getByRole('button', { name: /add section/i })).toBeEnabled()
  })

  it('disables submit when a title is blank', async () => {
    const { user } = renderPanel(plan(2))
    await user.clear(screen.getByLabelText('Section 1 title'))
    // Blanking makes it dirty → primary becomes "Approve with edits", which must be disabled.
    expect(screen.getByRole('button', { name: /approve with edits/i })).toBeDisabled()
  })

  it('adds and removes suggested-query chips', async () => {
    const { user } = renderPanel(plan(1))
    const input = screen.getByLabelText('Add suggested query to section 1')
    await user.type(input, 'pricing tiers{Enter}')
    expect(screen.getByText('pricing tiers')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Remove query pricing tiers' }))
    expect(screen.queryByText('pricing tiers')).not.toBeInTheDocument()
  })

  it('shows "already resumed" and refetches on 409', async () => {
    vi.spyOn(api, 'resumeRun').mockRejectedValue(new ApiError(409, 'run is not awaiting approval'))
    const { user, invalidate } = renderPanel(plan(2))

    await user.click(screen.getByRole('button', { name: 'Approve plan' }))

    expect(await screen.findByText(/already resumed/i)).toBeInTheDocument()
    await waitFor(() =>
      expect(invalidate).toHaveBeenCalledWith({ queryKey: runKeys.detail('r1') }),
    )
  })

  it('disables the controls while the resume is pending', async () => {
    vi.spyOn(api, 'resumeRun').mockReturnValue(new Promise(() => {}))
    const { user } = renderPanel(plan(2))

    await user.click(screen.getByRole('button', { name: 'Approve plan' }))

    await waitFor(() => expect(screen.getByRole('button', { name: 'Approve plan' })).toBeDisabled())
    expect(document.querySelector('.animate-spin')).not.toBeNull()
    expect(screen.getByLabelText('Section 1 title')).toBeDisabled()
  })

  it('is operable by keyboard (focus + Enter submits)', async () => {
    const resume = vi.spyOn(api, 'resumeRun').mockResolvedValue(undefined)
    const { user } = renderPanel(plan(1))

    const approve = screen.getByRole('button', { name: 'Approve plan' })
    approve.focus()
    expect(approve).toHaveFocus()
    await user.keyboard('{Enter}')

    await waitFor(() => expect(resume).toHaveBeenCalledWith('r1', { action: 'approve' }))
  })
})
