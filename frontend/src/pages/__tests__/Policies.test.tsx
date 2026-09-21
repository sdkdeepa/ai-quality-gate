import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Policies } from '../Policies'
import { api } from '../../api/client'

vi.mock('../../api/client', async () => {
  const actual = await vi.importActual<typeof import('../../api/client')>('../../api/client')
  return {
    ...actual,
    api: { ...actual.api, listPolicies: vi.fn(), getActivePolicy: vi.fn() },
  }
})

const POLICY = {
  id: 'policy-1',
  name: 'default',
  version: '1.0.0',
  required_metrics: [],
  min_pass_rate: 1.0,
  critical_case_action: 'block' as const,
  max_regression_tolerance: 0,
  regression_action: 'block' as const,
  latency_budget_ms: null,
  latency_budget_action: 'warn' as const,
  cost_budget_usd: null,
  cost_budget_action: 'warn' as const,
  created_at: '2026-09-19T00:00:00Z',
}

describe('Policies', () => {
  afterEach(() => {
    vi.resetAllMocks()
  })

  it('shows an empty state when no policies are registered', async () => {
    vi.mocked(api.listPolicies).mockResolvedValue([])
    vi.mocked(api.getActivePolicy).mockRejectedValue(new Error('none'))

    render(<Policies />)

    await waitFor(() => expect(screen.getByText(/no policies registered/i)).toBeInTheDocument())
  })

  it('renders a row per policy with its key settings', async () => {
    vi.mocked(api.listPolicies).mockResolvedValue([POLICY])
    vi.mocked(api.getActivePolicy).mockResolvedValue(POLICY)

    render(<Policies />)

    await waitFor(() => expect(screen.getAllByTestId('policy-row')).toHaveLength(1))
    expect(screen.getByText('100%')).toBeInTheDocument()
    expect(screen.getByText('block')).toBeInTheDocument()
  })

  it('marks the active policy distinctly from other registered policies', async () => {
    const other = { ...POLICY, id: 'policy-2', name: 'strict' }
    vi.mocked(api.listPolicies).mockResolvedValue([POLICY, other])
    vi.mocked(api.getActivePolicy).mockResolvedValue(other)

    render(<Policies />)

    await waitFor(() => expect(screen.getAllByTestId('policy-row')).toHaveLength(2))
    expect(screen.getByText('active')).toBeInTheDocument()
  })

  it('shows required metrics when a policy has them', async () => {
    const strict = {
      ...POLICY,
      required_metrics: [
        { metric_name: 'exact_match', min_score: 1.0, on_missing: 'block' as const, on_infrastructure_failure: 'block' as const },
      ],
    }
    vi.mocked(api.listPolicies).mockResolvedValue([strict])
    vi.mocked(api.getActivePolicy).mockResolvedValue(strict)

    render(<Policies />)

    await waitFor(() => expect(screen.getByText('exact_match')).toBeInTheDocument())
  })
})
