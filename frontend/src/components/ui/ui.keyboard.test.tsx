import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { Button } from './Button'
import { Tabs } from './Tabs'

function TabsHarness() {
  const [value, setValue] = useState('a')
  return (
    <Tabs
      value={value}
      onChange={setValue}
      items={[
        { value: 'a', label: 'Alpha' },
        { value: 'b', label: 'Beta' },
        { value: 'c', label: 'Gamma' },
      ]}
    />
  )
}

describe('UI kit keyboard nav', () => {
  it('Tabs uses roving tabindex and arrow keys move the active tab', async () => {
    const user = userEvent.setup()
    render(<TabsHarness />)
    const [alpha, beta] = screen.getAllByRole('tab')

    expect(alpha).toHaveAttribute('aria-selected', 'true')
    expect(alpha).toHaveAttribute('tabindex', '0')
    expect(beta).toHaveAttribute('tabindex', '-1')

    alpha.focus()
    await user.keyboard('{ArrowRight}')
    expect(beta).toHaveAttribute('aria-selected', 'true')
    expect(beta).toHaveFocus()

    await user.keyboard('{ArrowLeft}')
    expect(alpha).toHaveAttribute('aria-selected', 'true')
    expect(alpha).toHaveFocus()
  })

  it('interactive elements carry a visible focus ring', () => {
    render(
      <>
        <Button>Go</Button>
        <TabsHarness />
      </>,
    )
    expect(screen.getByRole('button', { name: 'Go' }).className).toContain('focus-visible:')
    for (const tab of screen.getAllByRole('tab')) {
      expect(tab.className).toContain('focus-visible:')
    }
  })

  it('Button Enter/Space activate, but disabled and loading block onClick', async () => {
    const user = userEvent.setup()
    const onClick = vi.fn()

    const { rerender } = render(<Button onClick={onClick}>Press</Button>)
    const btn = screen.getByRole('button', { name: 'Press' })
    btn.focus()
    await user.keyboard('{Enter}')
    await user.keyboard(' ')
    expect(onClick).toHaveBeenCalledTimes(2)

    onClick.mockClear()
    rerender(
      <Button onClick={onClick} disabled>
        Press
      </Button>,
    )
    await user.click(screen.getByRole('button', { name: 'Press' }))
    expect(onClick).not.toHaveBeenCalled()

    rerender(
      <Button onClick={onClick} loading>
        Press
      </Button>,
    )
    await user.click(screen.getByRole('button', { name: 'Press' }))
    expect(onClick).not.toHaveBeenCalled()
  })
})
