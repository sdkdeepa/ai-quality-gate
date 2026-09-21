import { api } from '../api/client'
import { useApiData } from '../api/useApiData'

export function Policies() {
  const policies = useApiData(() => api.listPolicies(), [])
  const active = useApiData(() => api.getActivePolicy(), [])

  return (
    <div>
      <h1>Policies</h1>
      <p className="muted">
        The most recently registered policy is always the active one — see{' '}
        <code>POST /api/v1/gate/policies</code>.
      </p>

      {policies.loading && <p>Loading…</p>}
      {policies.error && <p className="error-text">Failed to load policies: {policies.error}</p>}
      {!policies.loading && !policies.error && (policies.data?.length ?? 0) === 0 && (
        <p className="muted">No policies registered.</p>
      )}

      {(policies.data?.length ?? 0) > 0 && (
        <table className="data-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Version</th>
              <th>Min pass rate</th>
              <th>Critical action</th>
              <th>Regression tolerance</th>
              <th>Required metrics</th>
              <th>Latency budget</th>
              <th>Cost budget</th>
            </tr>
          </thead>
          <tbody>
            {policies.data!.map((policy) => (
              <tr
                key={policy.id}
                className={policy.id === active.data?.id ? 'row-active' : ''}
                data-testid="policy-row"
              >
                <td>
                  {policy.name}
                  {policy.id === active.data?.id && <span className="inline-tag"> active</span>}
                </td>
                <td>{policy.version}</td>
                <td>{(policy.min_pass_rate * 100).toFixed(0)}%</td>
                <td>{policy.critical_case_action}</td>
                <td>
                  {(policy.max_regression_tolerance * 100).toFixed(0)}% ({policy.regression_action})
                </td>
                <td>
                  {policy.required_metrics.length === 0 ? (
                    <span className="muted">none</span>
                  ) : (
                    policy.required_metrics.map((m) => m.metric_name).join(', ')
                  )}
                </td>
                <td>{policy.latency_budget_ms ? `${policy.latency_budget_ms}ms` : '-'}</td>
                <td>{policy.cost_budget_usd ? `$${policy.cost_budget_usd}` : '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
