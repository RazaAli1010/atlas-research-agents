import { describe, expect, it } from 'vitest'
import { absoluteTime, relativeTime } from './relativeTime'

const NOW = new Date('2026-07-23T12:00:00Z').getTime()

describe('relativeTime', () => {
  it('formats recent past as "just now"', () => {
    expect(relativeTime('2026-07-23T11:59:58Z', NOW)).toBe('just now')
  })

  it('formats minutes and hours ago', () => {
    expect(relativeTime('2026-07-23T11:58:00Z', NOW)).toBe('2 minutes ago')
    expect(relativeTime('2026-07-23T09:00:00Z', NOW)).toBe('3 hours ago')
  })

  it('formats future times', () => {
    expect(relativeTime('2026-07-23T12:05:00Z', NOW)).toBe('in 5 minutes')
  })

  it('returns empty string for invalid input', () => {
    expect(relativeTime('not-a-date', NOW)).toBe('')
    expect(absoluteTime('not-a-date')).toBe('')
  })
})
