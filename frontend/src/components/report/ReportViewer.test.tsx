import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ReportViewer } from './ReportViewer'
import type { Source } from '../../types'

const REPORT =
  '# Vector Database Pricing\n\n## Executive summary\n\nPinecone leads on price [1].\n\n## 1. Pricing\n\nDetails [1].\n\n## Sources\n1. [Pinecone](https://pinecone.io)'

const sources: Source[] = [
  { url: 'https://pinecone.io', title: 'Pinecone', snippet: 's', tool: 'web_search' },
]

function renderViewer(traceId: string | null = null) {
  return render(
    <ReportViewer reportMd={REPORT} sources={sources} runId="r1" traceId={traceId} />,
  )
}

describe('ReportViewer', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllEnvs()
  })

  it('renders [n] markers as superscript links to the source list', async () => {
    renderViewer()
    const citations = await screen.findAllByRole('link', { name: '1' })
    expect(citations.length).toBeGreaterThan(0)
    for (const c of citations) {
      expect(c).toHaveAttribute('href', '#source-1')
      expect(c.closest('sup')).not.toBeNull()
    }
    expect(document.getElementById('source-1')).not.toBeNull()
  })

  it('does not re-render the raw "## Sources" markdown list in the body', () => {
    const { container } = renderViewer()
    // The body's rendered ordered list would produce an <a> to pinecone with visible text
    // "Pinecone" only via our SourceList — the split removes the markdown Sources list.
    // The body markdown should not contain a second list item linking to the raw source.
    const bodyLists = container.querySelectorAll('.prose-atlas ol, .prose-atlas ul')
    expect(bodyLists.length).toBe(0)
  })

  it('copies the full markdown to the clipboard', async () => {
    // userEvent.setup() installs a working clipboard stub; read it back to prove the write.
    const user = userEvent.setup()
    renderViewer()
    await user.click(screen.getByRole('button', { name: /copy/i }))
    expect(await navigator.clipboard.readText()).toBe(REPORT)
  })

  it('downloads via the report.md endpoint', () => {
    renderViewer()
    const dl = screen.getByRole('link', { name: /download/i })
    expect(dl).toHaveAttribute('download')
    expect(dl.getAttribute('href')).toMatch(/\/api\/runs\/r1\/report\.md$/)
  })

  it('deep-links the LangSmith trace when base + traceId are set', () => {
    vi.stubEnv('VITE_LANGSMITH_BASE_URL', 'https://smith.langchain.com/o/o1/projects/p/p1')
    renderViewer('abc')
    const trace = screen.getByRole('link', { name: /open trace/i })
    expect(trace).toHaveAttribute('href', 'https://smith.langchain.com/o/o1/projects/p/p1/r/abc')
  })

  it('falls back to the LangSmith home when untraced (never a dead link)', () => {
    renderViewer(null)
    const trace = screen.getByRole('link', { name: /open trace/i })
    expect(trace.getAttribute('href')).not.toBe('#')
    expect(trace).toHaveAttribute('href', 'https://smith.langchain.com')
  })
})
