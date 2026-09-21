import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import { useApiData } from '../api/useApiData'
import { StatusBadge } from '../components/StatusBadge'
import type { GateDecision } from '../api/types'

export function RunDetail() {
  const { runId } = useParams<{ runId: string }>()
  const run = useApiData(() => api.getRun(runId!), [runId])
  const decisions = useApiData(() => api.listDecisions(runId!), [runId])
  const [gateError, setGateError] = useState<string | null>(null)
  const [gating, setGating] = useState(false)
  const [lastDecision, setLastDecision] = useState<GateDecision | null>(null)

  if (!runId) return <p className="error-text">No run id provided.</p>

  async function handleRunGate() {
    setGating(true)
    setGateError(null)
    try {
      const decision = await api.runGate(runId!)
      setLastDecision(decision)
    } catch (err) {
      setGateError(err instanceof ApiError ? err.detail : (err as Error).message)
    } finally {
      setGating(false)
    }
  }

  const allDecisions = lastDecision
    ? [lastDecision, ...(decisions.data ?? []).filter((d) => d.id !== lastDecision.id)]
    : (decisions.data ?? [])

  return (
    <div>
      <h1>
        Run <code>{runId}</code>
      </h1>

      {run.loading && <p>Loading…</p>}
      {run.error && <p className="error-text">Failed to load run: {run.error}</p>}

      {run.data && (
        <>
          <section className="card-grid">
            <div className="card">
              <div className="card-label">Dataset</div>
              <div className="card-value">
                {run.data.run.dataset_name}@{run.data.run.dataset_version}
              </div>
            </div>
            <div className="card">
              <div className="card-label">Provider / Model</div>
              <div className="card-value">
                {run.data.run.provider} / {run.data.run.model}
              </div>
            </div>
            <div className="card">
              <div className="card-label">Cases</div>
              <div className="card-value">
                {run.data.passed_count}/{run.data.case_count} passed
              </div>
            </div>
            <div className="card">
              <div className="card-label">Trace ID</div>
              <div className="card-value card-value--small">
                {run.data.run.trace_id ? <code>{run.data.run.trace_id}</code> : 'not traced'}
              </div>
            </div>
          </section>

          <h2>Gate decisions</h2>
          <button onClick={handleRunGate} disabled={gating}>
            {gating ? 'Running gate…' : 'Run gate'}
          </button>
          {gateError && <p className="error-text">{gateError}</p>}
          {decisions.loading && <p>Loading decisions…</p>}
          {allDecisions.length === 0 && !decisions.loading && (
            <p className="muted">No gate decisions yet for this run.</p>
          )}
          {allDecisions.length > 0 && (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Status</th>
                  <th>Policy</th>
                  <th>Reasons</th>
                  <th>Critical</th>
                  <th>Reports</th>
                </tr>
              </thead>
              <tbody>
                {allDecisions.map((decision) => (
                  <tr key={decision.id} data-testid="decision-row">
                    <td>
                      <StatusBadge status={decision.status} />
                    </td>
                    <td>v{decision.policy_version}</td>
                    <td>
                      {decision.reasons.length === 0 ? (
                        <span className="muted">none</span>
                      ) : (
                        <ul className="reason-list">
                          {decision.reasons.map((reason) => (
                            <li key={reason}>{reason}</li>
                          ))}
                        </ul>
                      )}
                    </td>
                    <td>{decision.critical_failures.length || '-'}</td>
                    <td>
                      <a href={api.reportJsonUrl(decision.id)}>JSON</a>
                      {' · '}
                      <a href={api.reportHtmlUrl(decision.id)}>HTML</a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <h2>Case results ({run.data.case_count})</h2>
          <table className="data-table">
            <thead>
              <tr>
                <th>Case</th>
                <th>Result</th>
                <th>Latency</th>
                <th>Tokens</th>
                <th>Cost</th>
                <th>Metrics</th>
              </tr>
            </thead>
            <tbody>
              {run.data.case_results.map((c) => (
                <tr
                  key={c.case_id}
                  className={c.critical_failure ? 'row-critical' : !c.passed ? 'row-fail' : ''}
                  data-testid="case-row"
                >
                  <td>
                    <code>{c.case_id}</code>
                  </td>
                  <td>
                    {c.passed ? 'PASS' : 'FAIL'}
                    {c.critical_failure ? ' (critical)' : ''}
                  </td>
                  <td>{c.latency_ms.toFixed(0)} ms</td>
                  <td>
                    {c.input_tokens}/{c.output_tokens}
                  </td>
                  <td>${c.estimated_cost.toFixed(4)}</td>
                  <td>
                    {c.metric_results.length === 0 ? (
                      <span className="muted">none</span>
                    ) : (
                      c.metric_results
                        .map((m) => `${m.metric_name}=${m.score.toFixed(2)}${m.passed ? '✓' : '✗'}`)
                        .join('; ')
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  )
}
