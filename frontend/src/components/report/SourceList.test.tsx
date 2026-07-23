import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { SourceList } from './SourceList'
import type { Source } from '../../types'

const sources: Source[] = [
  { url: 'https://pinecone.io/pricing', title: 'Pinecone pricing', snippet: 's', tool: 'web_search' },
  { url: 'https://docs.internal/rag', title: 'Internal doc', snippet: 's', tool: 'rag' },
  { url: '', title: '', snippet: '1200 * 12 = 14400', tool: 'calculator' },
]

describe('SourceList', () => {
  it('renders one anchored item per source with tool badges', () => {
    render(<SourceList sources={sources} />)

    expect(document.getElementById('source-1')).not.toBeNull()
    expect(document.getElementById('source-2')).not.toBeNull()
    expect(document.getElementById('source-3')).not.toBeNull()

    expect(screen.getByText('web')).toBeInTheDocument()
    expect(screen.getByText('rag')).toBeInTheDocument()
    expect(screen.getByText('calc')).toBeInTheDocument()
  })

  it('shows a favicon image for URL sources including the hostname', () => {
    render(<SourceList sources={[sources[0]]} />)
    const img = document.querySelector('#source-1 img') as HTMLImageElement | null
    expect(img).not.toBeNull()
    expect(img!.getAttribute('src')).toContain('pinecone.io')
  })

  it('renders no favicon image for a calculator source', () => {
    render(<SourceList sources={[sources[2]]} />)
    expect(document.querySelector('#source-1 img')).toBeNull()
    expect(screen.getByText('calc')).toBeInTheDocument()
  })

  it('renders an empty state when there are no sources', () => {
    render(<SourceList sources={[]} />)
    expect(screen.getByText('No sources were cited.')).toBeInTheDocument()
  })
})
