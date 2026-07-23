import { afterEach, describe, expect, it, vi } from 'vitest'
import { langsmithTraceUrl } from './langsmith'

afterEach(() => vi.unstubAllEnvs())

describe('langsmithTraceUrl', () => {
  it('composes ${base}/r/${traceId} when both are present', () => {
    vi.stubEnv('VITE_LANGSMITH_BASE_URL', 'https://smith.langchain.com/o/o1/projects/p/p1')
    expect(langsmithTraceUrl('abc')).toBe(
      'https://smith.langchain.com/o/o1/projects/p/p1/r/abc',
    )
  })

  it('trims a trailing slash on the base', () => {
    vi.stubEnv('VITE_LANGSMITH_BASE_URL', 'https://smith.langchain.com/p1/')
    expect(langsmithTraceUrl('abc')).toBe('https://smith.langchain.com/p1/r/abc')
  })

  it('returns null when the base env is unset', () => {
    vi.stubEnv('VITE_LANGSMITH_BASE_URL', '')
    expect(langsmithTraceUrl('abc')).toBeNull()
  })

  it('returns null when traceId is null', () => {
    vi.stubEnv('VITE_LANGSMITH_BASE_URL', 'https://smith.langchain.com/p1')
    expect(langsmithTraceUrl(null)).toBeNull()
  })
})
