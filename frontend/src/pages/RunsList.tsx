import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { useApiData } from '../api/useApiData'

export function RunsList() {
  const runs = useApiData(() => api.listRuns(), [])

  return (
    <div>
      <h1>Evaluation Runs</h1>

      {runs.loading && <p>Loading…</p>}
      {runs.error && <p className="error-text">Failed to load runs: {runs.error}</p>}
      {!runs.loading && !runs.error && (runs.data?.length ?? 0) === 0 && (
        <p className="muted">
          No evaluation runs yet. Run one via <code>POST /api/v1/evaluations/runs</code>.
        </p>
      )}
      {(runs.data?.length ?? 0) > 0 && (
        <table className="data-table">
          <thead>
            <tr>
              <th>Run ID</th>
              <th>Dataset</th>
              <th>Provider</th>
              <th>Model</th>
              <th>Status</th>
              <th>Cases</th>
              <th>Critical</th>
              <th>Started</th>
            </tr>
          </thead>
          <tbody>
            {runs.data!.map((summary) => (
              <tr key={summary.run.id} data-testid="run-row">
                <td>
                  <Link to={`/runs/${summary.run.id}`}>
                    <code>{summary.run.id.slice(0, 8)}</code>
                  </Link>
                </td>
                <td>
                  {summary.run.dataset_name}@{summary.run.dataset_version}
                </td>
                <td>{summary.run.provider}</td>
                <td>{summary.run.model}</td>
                <td>{summary.run.status}</td>
                <td>
                  {summary.passed_count}/{summary.case_count}
                </td>
                <td>
                  {summary.critical_failure_case_ids.length > 0
                    ? summary.critical_failure_case_ids.length
                    : '-'}
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
