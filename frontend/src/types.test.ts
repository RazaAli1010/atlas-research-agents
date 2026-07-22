import { describe, expect, it } from 'vitest'
import { ATLAS_EVENT_TYPES, type AtlasEvent, type AtlasEventType } from './types'
import { eventSamples } from './api/eventSamples'

// Runtime discriminator: touching every branch proves the union is exhaustive.
function describeEvent(ev: AtlasEvent): string {
  switch (ev.type) {
    case 'status':
      return ev.status
    case 'node_started':
      return ev.node
    case 'node_finished':
      return ev.summary
    case 'token':
      return ev.delta
    case 'interrupt':
      return `plan:${ev.payload.plan.length}`
    case 'usage':
      return String(ev.total_cost_usd)
    case 'review':
      return ev.review.verdict
    case 'done':
      return ev.report_md
    case 'error':
      return ev.message
    default: {
      const _exhaustive: never = ev
      return _exhaustive
    }
  }
}

describe('AtlasEvent envelope round-trip', () => {
  it('parses and narrows every checked-in sample', () => {
    for (const ev of eventSamples) {
      // JSON round-trip mirrors what arrives over the wire.
      const parsed = JSON.parse(JSON.stringify(ev)) as AtlasEvent
      expect(() => describeEvent(parsed)).not.toThrow()
      expect(ATLAS_EVENT_TYPES).toContain(parsed.type)
    }
  })

  it('ATLAS_EVENT_TYPES covers exactly the 9 variant types (no missing/extra)', () => {
    const sampleTypes = new Set(eventSamples.map((e) => e.type))
    const declared = new Set<AtlasEventType>(ATLAS_EVENT_TYPES)
    expect(declared.size).toBe(9)
    expect(sampleTypes).toEqual(declared)
  })
})
