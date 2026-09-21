import type { GateStatus } from '../api/types'

const LABELS: Record<string, string> = {
  pass: 'PASS',
  warn: 'WARN',
  block: 'BLOCK',
}

export function StatusBadge({ status }: { status: string | GateStatus }) {
  const normalized = status.toLowerCase()
  const label = LABELS[normalized] ?? status.toUpperCase()
  return (
    <span className={`status-badge status-badge--${normalized}`} data-testid="status-badge">
      {label}
    </span>
  )
}
