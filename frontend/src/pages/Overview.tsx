import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { useApiData } from '../api/useApiData'

export function Overview() {
  const status = useApiData(() => api.getStatus(), [])
  const runs = useApiData(() => api.listRuns(), [])
  const policy = useApiData(() => api.getActivePolicy(), [])

  const recentRuns = runs.data?.slice(0, 5) ?? []
  const totalRuns = runs.data?.length ?? 0
  const failedRuns = runs.data?.filter((r) => r.failed_count > 0).length ?? 0

  return (
    <div>
      <h1>Overview</h1>

      <section className="card-grid">
        <div className="card">
          <div className="card-label">App</div>
          <div className="card-value">
            {status.loading ? '…' : status.error ? 'unavailable' : status.data?.app_name}
          </div>
          <div className="card-sub">
            {status.data ? `v${status.data.version} · ${status.data.environment}` : ''}
          </div>
        </div>
        <div className="card">
          <div className="card-label">Total runs</div>
          <div className="card-value">{runs.loading ? '…' : totalRuns}</div>
        </div>
        <div className="card">
          <div className="card-label">Runs with failures</div>
          <div className="card-value">{runs.loading ? '…' : failedRuns}</div>
        </div>
        <div className="card">
          <div className="card-label">Active policy</div>
          <div className="card-value">
            {policy.loading ? '…' : policy.error ? 'none registered' : policy.data?.name}
          </div>
          <div className="card-sub">{policy.data ? `v${policy.data.version}` : ''}</div>
        </div>
      </section>

      <h2>Recent runs</h2>
      {runs.loading && <p>Loading…</p>}
      {runs.error && <p className="error-text">Failed to load runs: {runs.error}</p>}
      {!runs.loading && !runs.error && recentRuns.length === 0 && (
        <p className="muted">No evaluation runs yet.</p>
      )}
      {recentRuns.length > 0 && (
        <table className="data-table">
          <thead>
            <tr>
              <th>Run</th>
              <th>Dataset</th>
              <th>Provider / Model</th>
              <th>Cases</th>
              <th>Started</th>
            </tr>
          </thead>
          <tbody>
            {recentRuns.map((summary) => (
              <tr key={summary.run.id}>
                <td>
                  <Link to={`/runs/${summary.run.id}`}>{summary.run.id.slice(0, 8)}</Link>
                </td>
                <td>
                  {summary.run.dataset_name}@{summary.run.dataset_version}
                </td>
                <td>
                  {summary.run.provider} / {summary.run.model}
                </td>
                <td>
                  {summary.passed_count}/{summary.case_count} passed
                  {summary.critical_failure_case_ids.length > 0 && (
                    <span className="inline-warning"> · critical</span>
                  )}
                </td>
                <td>{new Date(summary.run.started_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
