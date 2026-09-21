import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError, API_BASE_URL } from '../client'

describe('api client', () => {
  const originalFetch = global.fetch

  beforeEach(() => {
    global.fetch = vi.fn()
  })

  afterEach(() => {
    global.fetch = originalFetch
    vi.restoreAllMocks()
  })

  it('resolves with parsed JSON on a 200 response', async () => {
    ;(global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => [{ name: 'ok' }],
    })

    const result = await api.listPolicies()

    expect(result).toEqual([{ name: 'ok' }])
  })

  it('calls the expected URL and method for listRuns', async () => {
    const fetchMock = global.fetch as ReturnType<typeof vi.fn>
    fetchMock.mockResolvedValue({ ok: true, json: async () => [] })

    await api.listRuns()

    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE_URL}/evaluations/runs`,
      expect.objectContaining({ headers: expect.objectContaining({ 'Content-Type': 'application/json' }) }),
    )
  })

  it('POSTs the run_id body when calling runGate', async () => {
    const fetchMock = global.fetch as ReturnType<typeof vi.fn>
    fetchMock.mockResolvedValue({ ok: true, json: async () => ({ id: 'd1' }) })

    await api.runGate('run-1')

    const [, init] = fetchMock.mock.calls[0]
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string)).toEqual({ run_id: 'run-1', policy_id: null })
  })

  it('throws an ApiError with the backend detail message on a non-ok response', async () => {
    ;(global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: false,
      status: 404,
      statusText: 'Not Found',
      json: async () => ({ detail: "no evaluation run 'x'" }),
    })

    await expect(api.getRun('x')).rejects.toMatchObject({
      status: 404,
      detail: "no evaluation run 'x'",
    })
  })

  it('falls back to statusText when the error body is not JSON', async () => {
    ;(global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: false,
      status: 500,
      statusText: 'Internal Server Error',
      json: async () => {
        throw new Error('not json')
      },
    })

    await expect(api.getRun('x')).rejects.toBeInstanceOf(ApiError)
    await expect(api.getRun('x')).rejects.toMatchObject({ detail: 'Internal Server Error' })
  })

  it('builds report download URLs without making a request', () => {
    expect(api.reportJsonUrl('d1')).toBe(`${API_BASE_URL}/reports/d1/json`)
    expect(api.reportHtmlUrl('d1')).toBe(`${API_BASE_URL}/reports/d1/html`)
  })

  it('omits the run_id query param from listDecisions when not given', async () => {
    const fetchMock = global.fetch as ReturnType<typeof vi.fn>
    fetchMock.mockResolvedValue({ ok: true, json: async () => [] })

    await api.listDecisions()

    expect(fetchMock).toHaveBeenCalledWith(`${API_BASE_URL}/gate/decisions`, expect.anything())
  })

  it('includes the run_id query param from listDecisions when given', async () => {
    const fetchMock = global.fetch as ReturnType<typeof vi.fn>
    fetchMock.mockResolvedValue({ ok: true, json: async () => [] })

    await api.listDecisions('run-42')

    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE_URL}/gate/decisions?run_id=run-42`,
      expect.anything(),
    )
  })
})
