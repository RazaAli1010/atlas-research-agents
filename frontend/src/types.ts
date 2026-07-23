// Shared TypeScript types — the single frontend source of truth (SHARED CONTEXT §7/§5).
// Mirrors the backend API contracts verbatim. Components/hooks import types from here only.

export type RunStatus =
  | 'planning'
  | 'awaiting_approval'
  | 'researching'
  | 'reviewing'
  | 'writing'
  | 'done'
  | 'failed'
export type ToolName = 'web_search' | 'rag' | 'calculator'

export interface Source {
  url: string
  title: string
  snippet: string
  tool: ToolName
}
export interface SectionPlan {
  id: string
  title: string
  objective: string
  suggested_queries: string[]
}
export interface SectionDraft {
  section_id: string
  content_md: string
  sources: Source[]
  revision: number
}
export interface Review {
  section_id: string
  verdict: 'approved' | 'revise'
  score: number
  feedback: string
}
export interface UsageEvent {
  node: string
  model: string
  input_tokens: number
  output_tokens: number
  cost_usd: number
}

// §7 SSE envelope — VERBATIM discriminated union.
export type AtlasEvent =
  | { type: 'status'; status: RunStatus }
  | { type: 'node_started'; node: string; section_id?: string }
  | { type: 'node_finished'; node: string; section_id?: string; summary: string }
  | { type: 'token'; node: string; delta: string }
  | { type: 'interrupt'; payload: { plan: SectionPlan[] } }
  | { type: 'usage'; event: UsageEvent; total_cost_usd: number }
  | { type: 'review'; review: Review }
  | { type: 'done'; report_md: string }
  | { type: 'error'; message: string }
export type AtlasEventType = AtlasEvent['type']
export const ATLAS_EVENT_TYPES = [
  'status',
  'node_started',
  'node_finished',
  'token',
  'interrupt',
  'usage',
  'review',
  'done',
  'error',
] as const satisfies readonly AtlasEventType[]

// HTTP response/request shapes (§7).
export interface CreateRunResponse {
  run_id: string
  thread_id: string
}
export interface RunSummary {
  run_id: string
  topic: string
  status: RunStatus
  created_at: string
  cost_usd: number
}
export interface RunDetail {
  run_id: string
  thread_id: string
  topic: string
  status: RunStatus
  created_at: string
  cost_usd: number
  plan: SectionPlan[]
  plan_approved: boolean
  drafts: SectionDraft[]
  reviews: Review[]
  revision_counts: Record<string, number>
  final_report_md: string
  usage_log: UsageEvent[]
  cost_breakdown: Record<string, number>
  trace_id: string | null // LangSmith root run id for the deep-link (F11); null when untraced
}
export type ResumeAction =
  | { action: 'approve' }
  | { action: 'edit'; plan: SectionPlan[] }
