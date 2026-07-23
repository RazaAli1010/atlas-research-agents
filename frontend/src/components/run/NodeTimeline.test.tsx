import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { NodeTimeline } from './NodeTimeline'
import type { RunView } from '../../lib/runView'

function view(overrides: Partial<RunView> = {}): RunView {
  return {
    stages: { plan: 'done', approval: 'done', research: 'active', review: 'pending', write: 'pending' },
    sections: [
      {
        id: 's1',
        title: 'Pricing tiers',
        objective: 'o',
        state: 'revising',
        revision: 1,
        maxRevisions: 2,
        lastReview: null,
        sourceCount: 0,
      },
      {
        id: 's2',
        title: 'Scale limits',
        objective: 'o',
        state: 'researching',
        revision: 0,
        maxRevisions: 2,
        lastReview: null,
        sourceCount: 0,
      },
    ],
    costTotal: 0,
    costByNode: {},
    writerDraft: '',
    reportMd: null,
    errorMessage: null,
    status: 'researching',
    ...overrides,
  }
}

describe('NodeTimeline', () => {
  it('renders all five graph stages', () => {
    render(<NodeTimeline view={view()} />)
    for (const label of ['Plan', 'Approval', 'Research', 'Review', 'Write']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
  })

  it('shows a rev chip for a section in a revision cycle', () => {
    render(<NodeTimeline view={view()} />)
    expect(screen.getByText('rev 1/2')).toBeInTheDocument()
  })

  it('surfaces parallel section rows independently', () => {
    render(<NodeTimeline view={view()} />)
    expect(screen.getByText('Pricing tiers')).toBeInTheDocument()
    expect(screen.getByText('Scale limits')).toBeInTheDocument()
  })

  it('marks the active stage with the pulse class and never a spinner', () => {
    const { container } = render(<NodeTimeline view={view()} />)
    expect(container.querySelector('.atlas-pulse')).not.toBeNull()
    expect(screen.queryByRole('status')).toBeNull()
  })
})
