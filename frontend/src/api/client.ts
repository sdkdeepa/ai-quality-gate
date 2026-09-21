import type {
  AppStatus,
  DatasetDetail,
  DatasetSummary,
  GateDecision,
  ReleasePolicy,
  RunDetail,
  RunSummary,
} from './types'

// Configurable so the built dashboard can point at any deployed backend
// without a rebuild-time constant baked in for local dev only.
export const API_BASE_URL: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? 'http://localhost:8000/api/v1'

export class ApiError extends Error {
  status: number
  detail: string

  constructor(status: number, detail: string) {
    super(`API error ${status}: ${detail}`)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = await response.json()
      detail = body.detail ?? body.message ?? detail
    } catch {
      // response body wasn't JSON — fall back to statusText
    }
    throw new ApiError(response.status, detail)
  }
  return response.json() as Promise<T>
}

export const api = {
  getStatus: () => request<AppStatus>('/status'),

  listRuns: () => request<RunSummary[]>('/evaluations/runs'),
  getRun: (runId: string) => request<RunDetail>(`/evaluations/runs/${runId}`),
  runEvaluation: (body: { dataset_name: string; dataset_version?: string; provider?: string }) =>
    request<RunSummary>('/evaluations/runs', { method: 'POST', body: JSON.stringify(body) }),

  listDecisions: (runId?: string) =>
    request<GateDecision[]>(runId ? `/gate/decisions?run_id=${runId}` : '/gate/decisions'),
  getDecision: (decisionId: string) => request<GateDecision>(`/gate/decisions/${decisionId}`),
  runGate: (runId: string, policyId?: string) =>
    request<GateDecision>('/gate/decisions', {
      method: 'POST',
      body: JSON.stringify({ run_id: runId, policy_id: policyId ?? null }),
    }),

  listPolicies: () => request<ReleasePolicy[]>('/gate/policies'),
  getActivePolicy: () => request<ReleasePolicy>('/gate/policies/active'),

  listDatasets: () => request<DatasetSummary[]>('/datasets'),
  getDataset: (name: string, version: string) =>
    request<DatasetDetail>(`/datasets/${encodeURIComponent(name)}/${encodeURIComponent(version)}`),

  reportJsonUrl: (decisionId: string) => `${API_BASE_URL}/reports/${decisionId}/json`,
  reportHtmlUrl: (decisionId: string) => `${API_BASE_URL}/reports/${decisionId}/html`,
}
