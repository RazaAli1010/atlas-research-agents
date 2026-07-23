import { describe, expect, it } from 'vitest'
import type { AtlasEvent, SectionPlan } from '../types'
import { deriveRunView } from './runView'

const PLAN: SectionPlan[] = [
  { id: 's1', title: 'Pricing', objective: 'Compare costs', suggested_queries: [] },
  { id: 's2', title: 'Scale', objective: 'Throughput limits', suggested_queries: [] },
]

const started = (node: string, section_id?: string): AtlasEvent => ({
  type: 'node_started',
  node,
  ...(section_id ? { section_id } : {}),
})
const finished = (node: string, section_id?: string): AtlasEvent => ({
  type: 'node_finished',
  node,
  summary: '',
  ...(section_id ? { section_id } : {}),
})
const review = (section_id: string, verdict: 'approved' | 'revise'): AtlasEvent => ({
  type: 'review',
  review: { section_id, verdict, score: verdict === 'approved' ? 0.9 : 0.4, feedback: 'x' },
})

describe('deriveRunView — sections', () => {
  it('renders two sections in different states simultaneously', () => {
    const events: AtlasEvent[] = [
      started('worker', 's1'),
      started('worker', 's2'),
      finished('worker', 's2'),
      review('s2', 'revise'),
    ]
    const view = deriveRunView(events, PLAN)
    expect(view.sections.find((s) => s.id === 's1')?.state).toBe('researching')
    expect(view.sections.find((s) => s.id === 's2')?.state).toBe('revising')
  })

  it('surfaces revision cycles and caps the counter', () => {
    const s2 = () =>
      deriveRunView(
        [
          started('worker', 's2'),
          finished('worker', 's2'),
          review('s2', 'revise'),
          started('worker', 's2'), // re-research after revise
        ],
        PLAN,
      ).sections.find((s) => s.id === 's2')!
    expect(s2().state).toBe('researching')
    expect(s2().revision).toBe(1)

    const twice = deriveRunView(
      [
        finished('worker', 's2'),
        review('s2', 'revise'),
        finished('worker', 's2'),
        review('s2', 'revise'),
      ],
      PLAN,
    ).sections.find((s) => s.id === 's2')!
    expect(twice.revision).toBe(2)
    expect(twice.revision).toBeLessThanOrEqual(twice.maxRevisions)
    expect(twice.lastReview?.verdict).toBe('revise')
  })

  it('pulls source counts from hydrated drafts', () => {
    const view = deriveRunView([review('s1', 'approved')], PLAN, [
      {
        section_id: 's1',
        content_md: 'body',
        revision: 0,
        sources: [
          { url: 'a', title: 'A', snippet: 's', tool: 'web_search' },
          { url: 'b', title: 'B', snippet: 's', tool: 'rag' },
        ],
      },
    ])
    expect(view.sections.find((s) => s.id === 's1')?.sourceCount).toBe(2)
  })
})

describe('deriveRunView — stages', () => {
  it('marks the active stage from status and earlier stages done', () => {
    const view = deriveRunView(
      [started('planner'), finished('planner'), { type: 'status', status: 'researching' }],
      PLAN,
    )
    expect(view.stages.plan).toBe('done')
    expect(view.stages.approval).toBe('done')
    expect(view.stages.research).toBe('active')
    expect(view.stages.write).toBe('pending')
  })

  it('is monotonic: a late planner event does not demote an active write stage', () => {
    const view = deriveRunView(
      [started('writer'), { type: 'status', status: 'writing' }, started('planner')],
      PLAN,
    )
    expect(view.stages.write).toBe('active')
    expect(view.stages.plan).toBe('done')
  })

  it('a finished run marks every stage done', () => {
    const view = deriveRunView([{ type: 'done', report_md: '# R' }], PLAN)
    expect(Object.values(view.stages).every((s) => s === 'done')).toBe(true)
    expect(view.reportMd).toBe('# R')
  })

  it('awaiting_approval makes approval the active stage', () => {
    const view = deriveRunView([{ type: 'status', status: 'awaiting_approval' }], PLAN)
    expect(view.stages.approval).toBe('active')
    expect(view.stages.research).toBe('pending')
  })
})

describe('deriveRunView — cost, writer, error', () => {
  it('accumulates cost per node and tracks the running total', () => {
    const events: AtlasEvent[] = [
      {
        type: 'usage',
        event: { node: 'planner', model: 'm', input_tokens: 1, output_tokens: 1, cost_usd: 0.01 },
        total_cost_usd: 0.01,
      },
      {
        type: 'usage',
        event: { node: 'worker', model: 'm', input_tokens: 1, output_tokens: 1, cost_usd: 0.02 },
        total_cost_usd: 0.03,
      },
    ]
    const view = deriveRunView(events, PLAN)
    expect(view.costByNode).toEqual({ planner: 0.01, worker: 0.02 })
    expect(view.costTotal).toBe(0.03)
  })

  it('concatenates writer token deltas exactly once (no double counting)', () => {
    const events: AtlasEvent[] = [
      { type: 'token', node: 'writer', delta: 'Hello ' },
      { type: 'token', node: 'writer', delta: 'world' },
    ]
    expect(deriveRunView(events, PLAN).writerDraft).toBe('Hello world')
  })

  it('is pure — repeated derivation of the same log is deep-equal (replay-safe)', () => {
    const events: AtlasEvent[] = [
      started('worker', 's1'),
      { type: 'token', node: 'writer', delta: 'a' },
      review('s1', 'approved'),
    ]
    expect(deriveRunView(events, PLAN)).toEqual(deriveRunView(events, PLAN))
  })

  it('an error flips non-approved sections to failed and records the message', () => {
    const view = deriveRunView([review('s1', 'approved'), { type: 'error', message: 'boom' }], PLAN)
    expect(view.errorMessage).toBe('boom')
    expect(view.sections.find((s) => s.id === 's1')?.state).toBe('approved')
    expect(view.sections.find((s) => s.id === 's2')?.state).toBe('failed')
    expect(view.status).toBe('failed')
  })
})
