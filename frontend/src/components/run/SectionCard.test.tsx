import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { SectionCard } from './SectionCard'
import type { SectionView } from '../../lib/runView'
import type { Review } from '../../types'

function section(overrides: Partial<SectionView> = {}): SectionView {
  return {
    id: 's1',
    title: 'Pricing tiers',
    objective: 'Compare per-vector storage costs',
    state: 'reviewing',
    revision: 0,
    maxRevisions: 2,
    lastReview: null,
    sourceCount: 3,
    ...overrides,
  }
}

const review = (verdict: 'approved' | 'revise', feedback = 'Tighten the cost table'): Review => ({
  section_id: 's1',
  verdict,
  score: verdict === 'approved' ? 0.88 : 0.42,
  feedback,
})

describe('SectionCard', () => {
  it('shows a revise review with its score and feedback excerpt', () => {
    render(<SectionCard section={section({ state: 'revising', lastReview: review('revise') })} />)
    expect(screen.getByText('0.42')).toBeInTheDocument()
    expect(screen.getByText('Tighten the cost table')).toBeInTheDocument()
    expect(screen.getByText('Revising')).toBeInTheDocument()
  })

  it('shows an approved review and source count', () => {
    render(<SectionCard section={section({ state: 'approved', lastReview: review('approved', '') })} />)
    expect(screen.getByText('0.88')).toBeInTheDocument()
    expect(screen.getByText('Approved')).toBeInTheDocument()
    expect(screen.getByText('3 src')).toBeInTheDocument()
  })

  it('keeps draft content collapsed until a draft is provided (run done)', async () => {
    const { rerender } = render(<SectionCard section={section({ state: 'approved' })} />)
    expect(screen.queryByRole('button', { name: /show draft/i })).toBeNull()

    rerender(<SectionCard section={section({ state: 'approved' })} contentMd="# Draft body" />)
    const toggle = screen.getByRole('button', { name: /show draft/i })
    expect(screen.queryByText('# Draft body')).toBeNull() // collapsed by default
    await userEvent.click(toggle)
    expect(screen.getByText('# Draft body')).toBeInTheDocument()
  })
})
