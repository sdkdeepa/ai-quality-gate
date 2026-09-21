import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RunsList } from '../RunsList'
import { api } from '../../api/client'

vi.mock('../../api/client', async () => {
  const actual = await vi.importActual<typeof import('../../api/client')>('../../api/client')
  return { ...actual, api: { ...actual.api, listRuns: vi.fn() } }
})

function renderWithRouter() {
  return render(
    <MemoryRouter>
      <RunsList />
    </MemoryRouter>,
  )
}

describe('RunsList', () => {
  afterEach(() => {
    vi.resetAllMocks()
  })

  it('shows an empty state when there are no runs', async () => {
    vi.mocked(api.listRuns).mockResolvedValue([])

    renderWithRouter()

    await waitFor(() => expect(screen.getByText(/no evaluation runs yet/i)).toBeInTheDocument())
  })

  it('renders one row per run with dataset, provider, and pass counts', async () => {
    vi.mocked(api.listRuns).mockResolvedValue([
      {
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
      },
    ])

    renderWithRouter()

    await waitFor(() => expect(screen.getAllByTestId('run-row')).toHaveLength(1))
    expect(screen.getByText(/support_bot@1.1.0/)).toBeInTheDocument()
    expect(screen.getByText('8/10')).toBeInTheDocument()
  })

  it('shows an error message when the request fails', async () => {
    vi.mocked(api.listRuns).mockRejectedValue(new Error('network down'))

    renderWithRouter()

    await waitFor(() => expect(screen.getByText(/failed to load runs/i)).toBeInTheDocument())
  })

  it('shows a critical-failure count when a run has one', async () => {
    vi.mocked(api.listRuns).mockResolvedValue([
      {
        run: {
          id: 'run-xyz',
          dataset_name: 'support_bot',
          dataset_version: '1.0.0',
          provider: 'deterministic',
          model: 'fixture-v1',
          started_at: '2026-09-19T00:00:00Z',
          completed_at: null,
          status: 'completed',
          trace_id: null,
        },
        case_count: 5,
        passed_count: 3,
        failed_count: 2,
        critical_failure_case_ids: ['c1', 'c2'],
      },
    ])

    renderWithRouter()

    await waitFor(() => expect(screen.getByTestId('run-row')).toBeInTheDocument())
    expect(screen.getByText('2')).toBeInTheDocument()
  })
})
