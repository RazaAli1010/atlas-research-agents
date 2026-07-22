// Typed fetch wrapper for the Atlas HTTP surface (§7). All network calls go through here.
import type {
  CreateRunResponse,
  ResumeAction,
  RunDetail,
  RunSummary,
} from '../types'

// Empty/undefined VITE_API_URL = same-origin (Vite dev proxy handles /api → :8000).
const API_BASE = (import.meta.env.VITE_API_URL ?? '').replace(/\/$/, '')

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, init)
  } catch (err) {
    throw new ApiError(0, err instanceof Error ? err.message : 'Network error')
  }
  if (!res.ok) {
    let message = res.statusText || `Request failed (${res.status})`
    try {
      const body = await res.json()
      if (body && typeof body.detail === 'string') message = body.detail
    } catch {
      /* non-JSON error body — keep the status text */
    }
    throw new ApiError(res.status, message)
  }
  // 202/204 and other empty bodies must not be parsed as JSON.
  if (res.status === 204 || res.status === 202) return undefined as T
  if (res.headers.get('content-length') === '0') return undefined as T
  const contentType = res.headers.get('content-type') ?? ''
  if (!contentType.includes('application/json')) return undefined as T
  return (await res.json()) as T
}

export const api = {
  createRun: (topic: string) =>
    request<CreateRunResponse>('/api/runs', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ topic }),
    }),
  listRuns: () => request<RunSummary[]>('/api/runs'),
  getRun: (id: string) => request<RunDetail>(`/api/runs/${id}`),
  resumeRun: (id: string, body: ResumeAction) =>
    request<void>(`/api/runs/${id}/resume`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    }),
  reportUrl: (id: string) => `${API_BASE}/api/runs/${id}/report.md`,
  eventsUrl: (id: string) => `${API_BASE}/api/runs/${id}/events`,
}
