import { describe, expect, it } from 'vitest'
import { linkifyCitations, splitReportBody } from './citations'

describe('linkifyCitations', () => {
  it('rewrites a bare [n] marker into a #source-n link', () => {
    expect(linkifyCitations('a [1] b')).toBe('a [1](#source-1) b')
  })

  it('rewrites multiple markers', () => {
    expect(linkifyCitations('x [1] y [12] z')).toBe('x [1](#source-1) y [12](#source-12) z')
  })

  it('leaves an already-formed link [n](url) untouched (lookahead)', () => {
    expect(linkifyCitations('[1](http://x)')).toBe('[1](http://x)')
  })

  it('leaves a titled link [Foo](url) untouched', () => {
    expect(linkifyCitations('[Foo](http://x)')).toBe('[Foo](http://x)')
  })

  it('leaves numbers in prose alone', () => {
    expect(linkifyCitations('item 1 of 3')).toBe('item 1 of 3')
  })
})

describe('splitReportBody', () => {
  it('strips the trailing ## Sources section', () => {
    const md = '# T\n\nBody [1].\n\n## Sources\n1. [x](http://x)\n'
    const { body, hadSources } = splitReportBody(md)
    expect(hadSources).toBe(true)
    expect(body).toBe('# T\n\nBody [1].')
    expect(body).not.toContain('## Sources')
  })

  it('splits at the LAST ## Sources heading', () => {
    const md = '# T\n\n## Sources\nstray\n\nmore body\n\n## Sources\n1. a'
    const { body } = splitReportBody(md)
    // Only the final heading is the split point; the earlier one stays in the body.
    expect(body).toBe('# T\n\n## Sources\nstray\n\nmore body')
  })

  it('ignores a non-heading line that merely contains "## Sources"', () => {
    const md = 'see the intro ## Sources line here\n\nbody'
    const { body, hadSources } = splitReportBody(md)
    expect(hadSources).toBe(false)
    expect(body).toBe(md)
  })

  it('returns the whole string when there is no ## Sources heading', () => {
    const md = '# T\n\nBody with no sources.'
    const { body, hadSources } = splitReportBody(md)
    expect(hadSources).toBe(false)
    expect(body).toBe(md)
  })
})
