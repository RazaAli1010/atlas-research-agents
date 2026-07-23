import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
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

function renderCard(props: Parameters<typeof SectionCard>[0]) {
  return render(
    <MemoryRouter>
      <SectionCard {...props} />
    </MemoryRouter>,
  )
}

const review = (verdict: 'approved' | 'revise', feedback = 'Tighten the cost table'): Review => ({
  section_id: 's1',
  verdict,
  score: verdict === 'approved' ? 0.88 : 0.42,
  feedback,
})

describe('SectionCard', () => {
  it('shows a revise review with its score and feedback excerpt', () => {
    renderCard({ section: section({ state: 'revising', lastReview: review('revise') }), runId: 'r1' })
    expect(screen.getByText('0.42')).toBeInTheDocument()
    expect(screen.getByText('Tighten the cost table')).toBeInTheDocument()
    expect(screen.getByText('Revising')).toBeInTheDocument()
  })

  it('shows an approved review and source count', () => {
    renderCard({
      section: section({ state: 'approved', lastReview: review('approved', '') }),
      runId: 'r1',
    })
    expect(screen.getByText('0.88')).toBeInTheDocument()
    expect(screen.getByText('Approved')).toBeInTheDocument()
    expect(screen.getByText('3 src')).toBeInTheDocument()
  })

  it('labels a section "Not approved" once the run is done', () => {
    renderCard({ section: section({ state: 'unapproved', lastReview: review('revise') }), runId: 'r1' })
    expect(screen.getByText('Not approved')).toBeInTheDocument()
  })

  it('links to the draft page only once a draft exists (run done)', () => {
    const { rerender } = renderCard({ section: section({ state: 'approved' }), runId: 'r1' })
    expect(screen.queryByRole('link', { name: /show draft/i })).toBeNull()

    rerender(
      <MemoryRouter>
        <SectionCard section={section({ state: 'approved' })} runId="r1" contentMd="# Draft body" />
      </MemoryRouter>,
    )
    const link = screen.getByRole('link', { name: /show draft/i })
    expect(link).toHaveAttribute('href', '/runs/r1/sections/s1')
  })
})
