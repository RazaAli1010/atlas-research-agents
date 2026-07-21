import { render, screen } from '@testing-library/react'
import App from './App'

describe('App shell', () => {
  it('renders the Atlas wordmark and sidebar nav', () => {
    render(<App />)
    expect(screen.getByText('Atlas')).toBeInTheDocument()
    expect(screen.getAllByText('New Run').length).toBeGreaterThan(0)
    expect(screen.getByText('History')).toBeInTheDocument()
  })
})
