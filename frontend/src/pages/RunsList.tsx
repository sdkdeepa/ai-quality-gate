import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import { useApiData } from '../api/useApiData'
import type { ProviderName } from '../api/types'

const PROVIDERS: ProviderName[] = ['deterministic', 'openai', 'gemini']

function NewRunForm() {
  const datasets = useApiData(() => api.listDatasets(), [])
  const navigate = useNavigate()

  const names = [...new Set(datasets.data?.map((d) => d.name) ?? [])]
  const [name, setName] = useState('')
  const [version, setVersion] = useState('')
  const [provider, setProvider] = useState<ProviderName>('deterministic')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  // Default to the first dataset/version once the list loads, so the form
  // is immediately submittable rather than starting on an empty option.
  // Both are set together in one state update (not two separate effects
  // racing each other) so there's never an intermediate render where
  // `name` has updated but `version` hasn't yet.
  useEffect(() => {
    if (!datasets.data || datasets.data.length === 0 || name) return
    setName(datasets.data[0].name)
    setVersion(datasets.data[0].version)
  }, [datasets.data, name])

  const versionsForName = datasets.data?.filter((d) => d.name === name).map((d) => d.version) ?? []
  // Only fires when the user picks a different dataset after the initial
  // default above has already set a matching version - resets `version`
  // to the newly-selected dataset's first available one.
  useEffect(() => {
    if (versionsForName.length > 0 && !versionsForName.includes(version)) {
      setVersion(versionsForName[0])
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name])

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    if (!name || !version) return
    setSubmitting(true)
    setSubmitError(null)
    try {
      const result = await api.runEvaluation({
        dataset_name: name,
        dataset_version: version,
        provider,
      })
      navigate(`/runs/${result.run.id}`)
    } catch (err) {
      setSubmitError(err instanceof ApiError ? err.detail : (err as Error).message)
      setSubmitting(false)
    }
  }

  if (datasets.loading) return <p className="muted">Loading datasets…</p>
  if (datasets.error) {
    return <p className="error-text">Failed to load datasets: {datasets.error}</p>
  }
  if (names.length === 0) {
    return <p className="muted">No datasets available to run.</p>
  }

  return (
    <form className="new-run-form" onSubmit={handleSubmit}>
      <label>
        Dataset
        <select value={name} onChange={(e) => setName(e.target.value)} disabled={submitting}>
          {names.map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
      </label>

      <label>
        Version
        <select value={version} onChange={(e) => setVersion(e.target.value)} disabled={submitting}>
          {versionsForName.map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
      </label>

      <label>
        Provider
        <select
          value={provider}
          onChange={(e) => setProvider(e.target.value as ProviderName)}
          disabled={submitting}
        >
          {PROVIDERS.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </label>

      <button type="submit" disabled={submitting || !name || !version}>
        {submitting ? 'Running…' : 'Run evaluation'}
      </button>

      {submitError && <p className="error-text">{submitError}</p>}
    </form>
  )
}

export function RunsList() {
  const runs = useApiData(() => api.listRuns(), [])

  return (
    <div>
      <h1>Evaluation Runs</h1>

      <h2>Run a new evaluation</h2>
      <NewRunForm />

      <h2>Past runs</h2>
      {runs.loading && <p>Loading…</p>}
      {runs.error && <p className="error-text">Failed to load runs: {runs.error}</p>}
      {!runs.loading && !runs.error && (runs.data?.length ?? 0) === 0 && (
        <p className="muted">No evaluation runs yet.</p>
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
