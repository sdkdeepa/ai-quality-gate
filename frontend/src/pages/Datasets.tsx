import { useState } from 'react'
import { api } from '../api/client'
import { useApiData } from '../api/useApiData'

export function Datasets() {
  const datasets = useApiData(() => api.listDatasets(), [])
  const [selected, setSelected] = useState<{ name: string; version: string } | null>(null)
  const detail = useApiData(
    () => (selected ? api.getDataset(selected.name, selected.version) : Promise.resolve(null)),
    [selected?.name, selected?.version],
  )

  return (
    <div>
      <h1>Datasets</h1>

      {datasets.loading && <p>Loading…</p>}
      {datasets.error && <p className="error-text">Failed to load datasets: {datasets.error}</p>}
      {!datasets.loading && !datasets.error && (datasets.data?.length ?? 0) === 0 && (
        <p className="muted">No datasets loaded.</p>
      )}

      {(datasets.data?.length ?? 0) > 0 && (
        <table className="data-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Version</th>
              <th>Cases</th>
              <th>Description</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {datasets.data!.map((dataset) => (
              <tr key={`${dataset.name}@${dataset.version}`} data-testid="dataset-row">
                <td>{dataset.name}</td>
                <td>{dataset.version}</td>
                <td>{dataset.case_count}</td>
                <td>{dataset.description}</td>
                <td>
                  <button
                    onClick={() => setSelected({ name: dataset.name, version: dataset.version })}
                  >
                    View cases
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {selected && (
        <>
          <h2>
            {selected.name}@{selected.version}
          </h2>
          {detail.loading && <p>Loading cases…</p>}
          {detail.error && <p className="error-text">Failed to load dataset: {detail.error}</p>}
          {detail.data && (
            <table className="data-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Category</th>
                  <th>Query</th>
                  <th>Critical</th>
                  <th>Tags</th>
                </tr>
              </thead>
              <tbody>
                {detail.data.cases.map((c) => (
                  <tr key={c.id} className={c.critical ? 'row-critical' : ''}>
                    <td>
                      <code>{c.id}</code>
                    </td>
                    <td>{c.category}</td>
                    <td>{c.query}</td>
                    <td>{c.critical ? 'yes' : '-'}</td>
                    <td>{c.tags.join(', ') || '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </div>
  )
}
