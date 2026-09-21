// Mirrors the backend's Pydantic response shapes (see
// backend/app/domain/, backend/app/api/). Kept intentionally loose in a
// few places (e.g. metadata as Record<string, unknown>) rather than
// re-deriving every field the dashboard doesn't render.

export type GateStatus = 'pass' | 'warn' | 'block'

export interface MetricResult {
  metric_name: string
  score: number
  threshold: number
  passed: boolean
  framework: string
  explanation: string | null
  metadata: Record<string, unknown>
}

export interface CaseResult {
  case_id: string
  response: string
  retrieved_context: string[]
  latency_ms: number
  input_tokens: number
  output_tokens: number
  estimated_cost: number
  metric_results: MetricResult[]
  passed: boolean
  critical_failure: boolean
  error: { error_type: string; message: string } | null
}

export interface EvaluationRun {
  id: string
  dataset_name: string
  dataset_version: string
  provider: string
  model: string
  started_at: string
  completed_at: string | null
  status: string
  trace_id: string | null
}

export interface RunSummary {
  run: EvaluationRun
  case_count: number
  passed_count: number
  failed_count: number
  critical_failure_case_ids: string[]
}

export interface RunDetail extends RunSummary {
  case_results: CaseResult[]
  metrics_by_framework: Record<string, Record<string, MetricResult[]>>
}

export interface RegressionSummary {
  baseline_version: number
  pass_rate_delta: number
  metric_deltas: Record<string, number>
  new_failures: string[]
  recovered_failures: string[]
}

export interface GateDecision {
  id: string
  run_id: string
  dataset_version: string
  provider: string
  model: string
  policy_id: string
  policy_version: string
  status: GateStatus
  reasons: string[]
  aggregate_metrics: Record<string, number>
  critical_failures: string[]
  framework_errors: Record<string, number>
  regression_summary: RegressionSummary | null
  baseline_version: number | null
  trace_id: string | null
  created_at: string
}

export interface RequiredMetricPolicy {
  metric_name: string
  min_score: number | null
  on_missing: 'block' | 'warn' | 'ignore'
  on_infrastructure_failure: 'block' | 'warn' | 'ignore'
}

export interface ReleasePolicy {
  id: string
  name: string
  version: string
  required_metrics: RequiredMetricPolicy[]
  min_pass_rate: number
  critical_case_action: 'block' | 'warn'
  max_regression_tolerance: number
  regression_action: 'block' | 'warn'
  latency_budget_ms: number | null
  latency_budget_action: 'block' | 'warn'
  cost_budget_usd: number | null
  cost_budget_action: 'block' | 'warn'
  created_at: string
}

export interface DatasetSummary {
  name: string
  version: string
  description: string
  created_at: string
  case_count: number
}

export interface EvaluationCase {
  id: string
  name: string
  category: string
  query: string
  expected_answer: string | null
  expected_behavior: string
  reference_context: string[]
  critical: boolean
  tags: string[]
  metadata: Record<string, unknown>
}

export interface DatasetDetail {
  id: string
  name: string
  version: string
  description: string
  created_at: string
  cases: EvaluationCase[]
}

export interface AppStatus {
  status: string
  app_name: string
  version: string
  environment: string
  uptime_seconds: number
  counts: {
    evaluation_cases: number
    evaluation_runs: number
  }
}
