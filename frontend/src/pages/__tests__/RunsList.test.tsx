import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RunsList } from '../RunsList'
import { api } from '../../api/client'

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

vi.mock('../../api/client', async () => {
  const actual = await vi.importActual<typeof import('../../api/client')>('../../api/client')
  return {
    ...actual,
    api: { ...actual.api, listRuns: vi.fn(), listDatasets: vi.fn(), runEvaluation: vi.fn() },
  }
})

function renderWithRouter() {
  return render(
    <MemoryRouter>
      <RunsList />
    </MemoryRouter>,
  )
}

const RUN_SUMMARY = {
  run: {
    id: 'run-abc12345',
    dataset_name: 'support_bot',
    dataset_version: '1.1.0',
    provider: 'deterministic',
    model: 'fixture-v1',
    started_at: '2026-09-19T00:00:00Z',
    completed_at: null,
    status: 'completed',
    trace_id: null,
  },
  case_count: 10,
  passed_count: 8,
  failed_count: 2,
  critical_failure_case_ids: [],
}

const DATASETS = [
  { name: 'support_bot', version: '1.0.0', description: 'd', created_at: '2026-09-19T00:00:00Z', case_count: 5 },
  { name: 'support_bot', version: '1.1.0', description: 'd', created_at: '2026-09-19T00:00:00Z', case_count: 10 },
  { name: 'other_bot', version: '2.0.0', description: 'd', created_at: '2026-09-19T00:00:00Z', case_count: 3 },
]

describe('RunsList', () => {
  afterEach(() => {
    vi.resetAllMocks()
  })

  it('shows an empty state when there are no runs', async () => {
    vi.mocked(api.listRuns).mockResolvedValue([])
    vi.mocked(api.listDatasets).mockResolvedValue([])

    renderWithRouter()

    await waitFor(() => expect(screen.getByText(/no evaluation runs yet/i)).toBeInTheDocument())
  })

  it('renders one row per run with dataset, provider, and pass counts', async () => {
    vi.mocked(api.listRuns).mockResolvedValue([RUN_SUMMARY])
    vi.mocked(api.listDatasets).mockResolvedValue([])

    renderWithRouter()

    await waitFor(() => expect(screen.getAllByTestId('run-row')).toHaveLength(1))
    expect(screen.getByText(/support_bot@1.1.0/)).toBeInTheDocument()
    expect(screen.getByText('8/10')).toBeInTheDocument()
  })

  it('shows an error message when the request fails', async () => {
    vi.mocked(api.listRuns).mockRejectedValue(new Error('network down'))
    vi.mocked(api.listDatasets).mockResolvedValue([])

    renderWithRouter()

    await waitFor(() => expect(screen.getByText(/failed to load runs/i)).toBeInTheDocument())
  })

  it('shows a critical-failure count when a run has one', async () => {
    vi.mocked(api.listRuns).mockResolvedValue([
      { ...RUN_SUMMARY, case_count: 5, passed_count: 3, critical_failure_case_ids: ['c1', 'c2'] },
    ])
    vi.mocked(api.listDatasets).mockResolvedValue([])

    renderWithRouter()

    await waitFor(() => expect(screen.getByTestId('run-row')).toBeInTheDocument())
    expect(screen.getByText('2')).toBeInTheDocument()
  })

  describe('new evaluation form', () => {
    it('populates dataset and version dropdowns from listDatasets, deduplicating names', async () => {
      vi.mocked(api.listRuns).mockResolvedValue([])
      vi.mocked(api.listDatasets).mockResolvedValue(DATASETS)

      renderWithRouter()

      await waitFor(() => expect(screen.getByLabelText('Dataset')).toBeInTheDocument())
      const datasetSelect = screen.getByLabelText('Dataset') as HTMLSelectElement
      const options = Array.from(datasetSelect.options).map((o) => o.value)
      expect(options).toEqual(['support_bot', 'other_bot'])
    })

    it('defaults to the first dataset and its first version', async () => {
      vi.mocked(api.listRuns).mockResolvedValue([])
      vi.mocked(api.listDatasets).mockResolvedValue(DATASETS)

      renderWithRouter()

      await waitFor(() => expect(screen.getByLabelText('Dataset')).toHaveValue('support_bot'))
      expect(screen.getByLabelText('Version')).toHaveValue('1.0.0')
    })

    it('updates the version options when a different dataset is selected', async () => {
      vi.mocked(api.listRuns).mockResolvedValue([])
      vi.mocked(api.listDatasets).mockResolvedValue(DATASETS)

      renderWithRouter()
      await waitFor(() => expect(screen.getByLabelText('Dataset')).toHaveValue('support_bot'))

      await userEvent.selectOptions(screen.getByLabelText('Dataset'), 'other_bot')

      await waitFor(() => expect(screen.getByLabelText('Version')).toHaveValue('2.0.0'))
    })

    it('shows an empty state when no datasets exist to run', async () => {
      vi.mocked(api.listRuns).mockResolvedValue([])
      vi.mocked(api.listDatasets).mockResolvedValue([])

      renderWithRouter()

      await waitFor(() =>
        expect(screen.getByText(/no datasets available to run/i)).toBeInTheDocument(),
      )
    })

    it('submits the selected dataset/version/provider and navigates to the new run', async () => {
      vi.mocked(api.listRuns).mockResolvedValue([])
      vi.mocked(api.listDatasets).mockResolvedValue(DATASETS)
      vi.mocked(api.runEvaluation).mockResolvedValue({
        ...RUN_SUMMARY,
        run: { ...RUN_SUMMARY.run, id: 'new-run-id' },
      })

      renderWithRouter()
      await waitFor(() => expect(screen.getByLabelText('Dataset')).toHaveValue('support_bot'))

      await userEvent.click(screen.getByRole('button', { name: /run evaluation/i }))

      await waitFor(() => expect(api.runEvaluation).toHaveBeenCalledWith({
        dataset_name: 'support_bot',
        dataset_version: '1.0.0',
        provider: 'deterministic',
      }))
      expect(mockNavigate).toHaveBeenCalledWith('/runs/new-run-id')
    })

    it('shows an error and does not navigate when the submission fails', async () => {
      vi.mocked(api.listRuns).mockResolvedValue([])
      vi.mocked(api.listDatasets).mockResolvedValue(DATASETS)
      vi.mocked(api.runEvaluation).mockRejectedValue(new Error('provider misconfigured'))

      renderWithRouter()
      await waitFor(() => expect(screen.getByLabelText('Dataset')).toHaveValue('support_bot'))

      await userEvent.click(screen.getByRole('button', { name: /run evaluation/i }))

      await waitFor(() => expect(screen.getByText('provider misconfigured')).toBeInTheDocument())
      expect(mockNavigate).not.toHaveBeenCalled()
    })

    it('disables the submit button while the run is in flight', async () => {
      vi.mocked(api.listRuns).mockResolvedValue([])
      vi.mocked(api.listDatasets).mockResolvedValue(DATASETS)
      let resolveRun: (v: typeof RUN_SUMMARY) => void = () => {}
      vi.mocked(api.runEvaluation).mockReturnValue(
        new Promise((resolve) => {
          resolveRun = resolve
        }),
      )

      renderWithRouter()
      await waitFor(() => expect(screen.getByLabelText('Dataset')).toHaveValue('support_bot'))

      await userEvent.click(screen.getByRole('button', { name: /run evaluation/i }))

      expect(screen.getByRole('button', { name: /running/i })).toBeDisabled()
      resolveRun(RUN_SUMMARY)
    })
  })
})
