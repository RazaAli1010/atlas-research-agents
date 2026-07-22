import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api } from './client'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

describe('api client', () => {
  afterEach(() => vi.restoreAllMocks())

  it('createRun POSTs {topic} and returns {run_id, thread_id}', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(jsonResponse({ run_id: 'r1', thread_id: 't1' }, 201))

    const res = await api.createRun('vector db pricing')
    expect(res).toEqual({ run_id: 'r1', thread_id: 't1' })

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/runs')
    expect(init?.method).toBe('POST')
    expect(JSON.parse(init?.body as string)).toEqual({ topic: 'vector db pricing' })
  })

  it('throws ApiError with the status on a 500', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      jsonResponse({ detail: 'boom' }, 500),
    )
    const err = await api.listRuns().catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(500)
    expect(err.message).toBe('boom')
  })

  it('resumeRun resolves on a 202 empty body without calling res.json()', async () => {
    const res = new Response(null, { status: 202 })
    const jsonSpy = vi.spyOn(res, 'json')
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(res)

    await expect(api.resumeRun('r1', { action: 'approve' })).resolves.toBeUndefined()
    expect(jsonSpy).not.toHaveBeenCalled()
  })

  it('reportUrl / eventsUrl build same-origin URLs when VITE_API_URL is empty', () => {
    expect(api.reportUrl('r1')).toBe('/api/runs/r1/report.md')
    expect(api.eventsUrl('r1')).toBe('/api/runs/r1/events')
  })
})
