import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RunDetail } from '../RunDetail'
import { api } from '../../api/client'

vi.mock('../../api/client', async () => {
  const actual = await vi.importActual<typeof import('../../api/client')>('../../api/client')
  return {
    ...actual,
    api: {
      ...actual.api,
      getRun: vi.fn(),
      listDecisions: vi.fn(),
      runGate: vi.fn(),
    },
  }
})

const RUN_DETAIL = {
  run: {
    id: 'run-1',
    dataset_name: 'support_bot',
    dataset_version: '1.0.0',
    provider: 'deterministic',
    model: 'fixture-v1',
    started_at: '2026-09-19T00:00:00Z',
    completed_at: '2026-09-19T00:01:00Z',
    status: 'completed',
    trace_id: 'abc123',
  },
  case_count: 1,
  passed_count: 0,
  failed_count: 1,
  critical_failure_case_ids: ['c1'],
  case_results: [
    {
      case_id: 'c1',
      response: 'wrong answer',
      retrieved_context: [],
      latency_ms: 120,
      input_tokens: 5,
      output_tokens: 5,
      estimated_cost: 0.001,
      metric_results: [
        {
          metric_name: 'exact_match',
          score: 0,
          threshold: 1,
          passed: false,
          framework: 'deterministic',
          explanation: null,
          metadata: {},
        },
      ],
      passed: false,
      critical_failure: true,
      error: null,
    },
  ],
  metrics_by_framework: {},
}

function renderRunDetail() {
  return render(
    <MemoryRouter initialEntries={['/runs/run-1']}>
      <Routes>
        <Route path="/runs/:runId" element={<RunDetail />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('RunDetail', () => {
  afterEach(() => {
    vi.resetAllMocks()
  })

  it('renders run metadata and the per-case results table', async () => {
    vi.mocked(api.getRun).mockResolvedValue(RUN_DETAIL)
    vi.mocked(api.listDecisions).mockResolvedValue([])

    renderRunDetail()

    await waitFor(() => expect(screen.getByText(/support_bot@1.0.0/)).toBeInTheDocument())
    expect(screen.getByText('abc123')).toBeInTheDocument()
    expect(screen.getByTestId('case-row')).toBeInTheDocument()
    expect(screen.getByText(/FAIL \(critical\)/)).toBeInTheDocument()
  })

  it('shows "not traced" when the run has no trace id', async () => {
    vi.mocked(api.getRun).mockResolvedValue({
      ...RUN_DETAIL,
      run: { ...RUN_DETAIL.run, trace_id: null },
    })
    vi.mocked(api.listDecisions).mockResolvedValue([])

    renderRunDetail()

    await waitFor(() => expect(screen.getByText('not traced')).toBeInTheDocument())
  })

  it('renders existing gate decisions with a status badge and report links', async () => {
    vi.mocked(api.getRun).mockResolvedValue(RUN_DETAIL)
    vi.mocked(api.listDecisions).mockResolvedValue([
      {
        id: 'decision-1',
        run_id: 'run-1',
        dataset_version: '1.0.0',
        provider: 'deterministic',
        model: 'fixture-v1',
        policy_id: 'policy-1',
        policy_version: '1.0.0',
        status: 'block',
        reasons: ['critical case c1 failed'],
        aggregate_metrics: {},
        critical_failures: ['c1'],
        framework_errors: {},
        regression_summary: null,
        baseline_version: null,
        trace_id: 'abc123',
        created_at: '2026-09-19T00:02:00Z',
      },
    ])

    renderRunDetail()

    await waitFor(() => expect(screen.getByTestId('status-badge')).toHaveTextContent('BLOCK'))
    expect(screen.getByText('critical case c1 failed')).toBeInTheDocument()
    expect(screen.getByText('JSON')).toHaveAttribute('href', expect.stringContaining('/reports/decision-1/json'))
  })

  it('runs the gate and displays the resulting decision when the button is clicked', async () => {
    vi.mocked(api.getRun).mockResolvedValue(RUN_DETAIL)
    vi.mocked(api.listDecisions).mockResolvedValue([])
    vi.mocked(api.runGate).mockResolvedValue({
      id: 'decision-new',
      run_id: 'run-1',
      dataset_version: '1.0.0',
      provider: 'deterministic',
      model: 'fixture-v1',
      policy_id: 'policy-1',
      policy_version: '1.0.0',
      status: 'pass',
      reasons: [],
      aggregate_metrics: {},
      critical_failures: [],
      framework_errors: {},
      regression_summary: null,
      baseline_version: null,
      trace_id: null,
      created_at: '2026-09-19T00:03:00Z',
    })

    renderRunDetail()
    await waitFor(() => expect(screen.getByText(/no gate decisions yet/i)).toBeInTheDocument())

    await userEvent.click(screen.getByRole('button', { name: /run gate/i }))

    await waitFor(() => expect(screen.getByTestId('status-badge')).toHaveTextContent('PASS'))
    expect(api.runGate).toHaveBeenCalledWith('run-1')
  })

  it('shows an error message if running the gate fails', async () => {
    vi.mocked(api.getRun).mockResolvedValue(RUN_DETAIL)
    vi.mocked(api.listDecisions).mockResolvedValue([])
    vi.mocked(api.runGate).mockRejectedValue(new Error('no policy registered'))

    renderRunDetail()
    await waitFor(() => expect(screen.getByRole('button', { name: /run gate/i })).toBeEnabled())

    await userEvent.click(screen.getByRole('button', { name: /run gate/i }))

    await waitFor(() => expect(screen.getByText('no policy registered')).toBeInTheDocument())
  })
})
