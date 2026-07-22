// One checked-in sample per AtlasEvent variant — used by the envelope round-trip test
// (F10 acceptance). `satisfies` gives compile-time proof each object is a valid AtlasEvent.
import type { AtlasEvent } from '../types'

export const eventSamples = [
  { type: 'status', status: 'researching' },
  { type: 'node_started', node: 'worker', section_id: 's1' },
  { type: 'node_finished', node: 'planner', summary: 'Drafted 4 sections' },
  { type: 'token', node: 'writer', delta: 'Vector ' },
  {
    type: 'interrupt',
    payload: {
      plan: [
        {
          id: 's1',
          title: 'Pricing tiers',
          objective: 'Compare per-vector storage costs',
          suggested_queries: ['pinecone pricing', 'weaviate pricing'],
        },
      ],
    },
  },
  {
    type: 'usage',
    event: {
      node: 'planner',
      model: 'gpt-4o-mini',
      input_tokens: 1200,
      output_tokens: 340,
      cost_usd: 0.0021,
    },
    total_cost_usd: 0.0021,
  },
  {
    type: 'review',
    review: {
      section_id: 's1',
      verdict: 'approved',
      score: 0.86,
      feedback: '',
    },
  },
  { type: 'done', report_md: '# Vector Database Pricing\n\nFinal report body…' },
  { type: 'error', message: 'Run cost ceiling exceeded' },
] as const satisfies readonly AtlasEvent[]
