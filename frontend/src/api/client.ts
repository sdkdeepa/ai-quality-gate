import type {
  AppStatus,
  DatasetDetail,
  DatasetSummary,
  GateDecision,
  ProviderName,
  ReleasePolicy,
  RunDetail,
  RunSummary,
} from './types'

declare global {
  interface Window {
    // Written by docker-entrypoint.sh at container startup (see
    // index.html / public/env-config.js); absent or empty outside Docker.
    __APP_CONFIG__?: { API_BASE_URL?: string }
  }
}

// Resolution order: a Docker container's runtime-injected config (so one
// built image can be pointed at any backend without a rebuild) -> Vite's
// build-time env var (local dev / a build meant for one fixed backend) ->
// the local-dev default. See Sprint 11's DECISIONS.md entry for why a
// runtime value takes priority over the build-time one.
export const API_BASE_URL: string =
  window.__APP_CONFIG__?.API_BASE_URL ||
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ||
  'http://localhost:8000/api/v1'

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
  runEvaluation: (body: { dataset_name: string; dataset_version?: string; provider?: ProviderName }) =>
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
