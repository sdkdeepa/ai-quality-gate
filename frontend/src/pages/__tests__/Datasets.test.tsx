import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Datasets } from '../Datasets'
import { api } from '../../api/client'

vi.mock('../../api/client', async () => {
  const actual = await vi.importActual<typeof import('../../api/client')>('../../api/client')
  return {
    ...actual,
    api: { ...actual.api, listDatasets: vi.fn(), getDataset: vi.fn() },
  }
})

const DATASET_SUMMARY = {
  name: 'support_bot',
  version: '1.1.0',
  description: 'Customer support golden dataset',
  created_at: '2026-09-19T00:00:00Z',
  case_count: 2,
}

describe('Datasets', () => {
  afterEach(() => {
    vi.resetAllMocks()
  })

  it('shows an empty state when no datasets are loaded', async () => {
    vi.mocked(api.listDatasets).mockResolvedValue([])

    render(<Datasets />)

    await waitFor(() => expect(screen.getByText(/no datasets loaded/i)).toBeInTheDocument())
  })

  it('renders a row per dataset version', async () => {
    vi.mocked(api.listDatasets).mockResolvedValue([DATASET_SUMMARY])

    render(<Datasets />)

    await waitFor(() => expect(screen.getAllByTestId('dataset-row')).toHaveLength(1))
    expect(screen.getByText('support_bot')).toBeInTheDocument()
    expect(screen.getByText('1.1.0')).toBeInTheDocument()
  })

  it('loads and displays a dataset\'s cases when "View cases" is clicked', async () => {
    vi.mocked(api.listDatasets).mockResolvedValue([DATASET_SUMMARY])
    vi.mocked(api.getDataset).mockResolvedValue({
      id: 'support_bot@1.1.0',
      name: 'support_bot',
      version: '1.1.0',
      description: 'Customer support golden dataset',
      created_at: '2026-09-19T00:00:00Z',
      cases: [
        {
          id: 'case-1',
          name: 'n',
          category: 'answer',
          query: 'What is your return policy?',
          expected_answer: null,
          expected_behavior: 'answer',
          reference_context: [],
          critical: true,
          tags: ['policy'],
          metadata: {},
        },
      ],
    })

    render(<Datasets />)
    await waitFor(() => expect(screen.getByRole('button', { name: /view cases/i })).toBeInTheDocument())

    await userEvent.click(screen.getByRole('button', { name: /view cases/i }))

    await waitFor(() => expect(screen.getByText('What is your return policy?')).toBeInTheDocument())
    expect(api.getDataset).toHaveBeenCalledWith('support_bot', '1.1.0')
    expect(screen.getByText('yes')).toBeInTheDocument() // critical column
  })

  it('shows an error message when the dataset list fails to load', async () => {
    vi.mocked(api.listDatasets).mockRejectedValue(new Error('boom'))

    render(<Datasets />)

    await waitFor(() => expect(screen.getByText(/failed to load datasets/i)).toBeInTheDocument())
  })
})
