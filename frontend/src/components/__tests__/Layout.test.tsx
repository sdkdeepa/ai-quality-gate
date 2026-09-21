import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { Layout } from '../Layout'

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<div>overview-content</div>} />
          <Route path="runs" element={<div>runs-content</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

describe('Layout', () => {
  it('renders the four top-level navigation links (Run Detail is reached via drill-down, not a nav item)', () => {
    renderAt('/')

    expect(screen.getByRole('link', { name: 'Overview' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Evaluation Runs' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Policies' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Datasets' })).toBeInTheDocument()
  })

  it('renders the matched child route inside the content area', () => {
    renderAt('/runs')

    expect(screen.getByText('runs-content')).toBeInTheDocument()
  })

  it('marks the active route link distinctly from inactive ones', () => {
    renderAt('/')

    expect(screen.getByRole('link', { name: 'Overview' })).toHaveClass('nav-link--active')
    expect(screen.getByRole('link', { name: 'Evaluation Runs' })).not.toHaveClass(
      'nav-link--active',
    )
  })
})
