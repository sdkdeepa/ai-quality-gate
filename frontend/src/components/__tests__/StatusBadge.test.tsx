import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { StatusBadge } from '../StatusBadge'

describe('StatusBadge', () => {
  it('renders PASS in uppercase for a "pass" status', () => {
    render(<StatusBadge status="pass" />)
    expect(screen.getByTestId('status-badge')).toHaveTextContent('PASS')
  })

  it('renders WARN for a "warn" status', () => {
    render(<StatusBadge status="warn" />)
    expect(screen.getByTestId('status-badge')).toHaveTextContent('WARN')
  })

  it('renders BLOCK for a "block" status', () => {
    render(<StatusBadge status="block" />)
    expect(screen.getByTestId('status-badge')).toHaveTextContent('BLOCK')
  })

  it('is case-insensitive to the input status', () => {
    render(<StatusBadge status="BLOCK" />)
    expect(screen.getByTestId('status-badge')).toHaveTextContent('BLOCK')
  })

  it('applies a status-specific CSS class so PASS/WARN/BLOCK are colour-coded', () => {
    const { rerender } = render(<StatusBadge status="pass" />)
    expect(screen.getByTestId('status-badge')).toHaveClass('status-badge--pass')

    rerender(<StatusBadge status="block" />)
    expect(screen.getByTestId('status-badge')).toHaveClass('status-badge--block')
  })

  it('falls back to the raw uppercased value for an unrecognized status', () => {
    render(<StatusBadge status="unknown" />)
    expect(screen.getByTestId('status-badge')).toHaveTextContent('UNKNOWN')
  })
})
