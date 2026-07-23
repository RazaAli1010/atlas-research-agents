import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { CostMeter } from './CostMeter'

describe('CostMeter', () => {
  it('renders the total in monospace with 4 decimals', () => {
    render(<CostMeter costTotal={0.0021} costByNode={{}} />)
    expect(screen.getByText('$0.0021')).toBeInTheDocument()
  })

  it('applies the warn color past 80% of the ceiling', () => {
    render(<CostMeter costTotal={1.3} costByNode={{}} />)
    expect(screen.getByText('$1.3000')).toHaveClass('text-warn')
  })

  it('stays neutral below the warn threshold', () => {
    render(<CostMeter costTotal={0.5} costByNode={{}} />)
    expect(screen.getByText('$0.5000')).not.toHaveClass('text-warn')
  })

  it('exposes a per-node breakdown on hover', async () => {
    render(<CostMeter costTotal={0.03} costByNode={{ planner: 0.01, worker: 0.02 }} />)
    await userEvent.hover(screen.getByText('$0.0300'))
    expect(screen.getByText('planner')).toBeInTheDocument()
    expect(screen.getByText('$0.0100')).toBeInTheDocument()
    expect(screen.getByText('worker')).toBeInTheDocument()
    expect(screen.getByText('$0.0200')).toBeInTheDocument()
  })
})
