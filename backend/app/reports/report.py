"""Sprint 10: a downloadable, fully self-contained snapshot of one
`GateDecision` plus everything needed to understand it without a second
API call — the run it decided about, every case's full result, and the
run-wide aggregates a reader would otherwise have to compute by hand.

This is a presentation/export concern layered over Sprint 8's
`PolicyEngine`/`GateDecision`, not a new source of truth: every field here
already exists somewhere in `GateDecision`/`EvaluationRun`/`CaseResult`.
`build_report()` only assembles and computes a few run-wide summaries
(pass rate, total cost, mean latency, total tokens) that are cheap to
derive from `case_results` and would otherwise need recomputing by every
caller that wants them.
"""

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from app.domain.case_result import CaseResult
from app.domain.enums import GateStatus
from app.domain.evaluation_run import EvaluationRun
from app.domain.gate_decision import GateDecision, RegressionSummary


class Report(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Decision identity + policy (requirement: "PASS/WARN/BLOCK", "policy version")
    decision_id: str
    status: GateStatus
    reasons: list[str]
    policy_id: str
    policy_version: str

    # Run metadata (requirement: "run metadata", "dataset version", "provider/model", "trace ID")
    run_id: str
    dataset_name: str
    dataset_version: str
    provider: str
    model: str
    started_at: datetime
    completed_at: datetime | None
    trace_id: str | None

    # Aggregates (requirement: "aggregate metrics", "critical failures",
    # "regressions", "framework errors", "latency", "token usage",
    # "estimated cost")
    aggregate_metrics: dict[str, float]
    critical_failures: list[str]
    framework_errors: dict[str, int]
    regression_summary: RegressionSummary | None
    baseline_version: int | None
    total_cases: int
    passed_cases: int
    pass_rate: float
    total_estimated_cost: float
    mean_latency_ms: float
    total_input_tokens: int
    total_output_tokens: int

    # Per-case results (requirement: "per-case results") — CaseResult
    # already carries each case's own metric_results/latency/tokens/cost/
    # critical_failure/error, so nothing is re-derived here.
    case_results: list[CaseResult]


def build_report(
    decision: GateDecision, run: EvaluationRun, case_results: list[CaseResult]
) -> Report:
    total_cases = len(case_results)
    passed_cases = sum(1 for c in case_results if c.passed)
    return Report(
        decision_id=decision.id,
        status=decision.status,
        reasons=decision.reasons,
        policy_id=decision.policy_id,
        policy_version=decision.policy_version,
        run_id=run.id,
        dataset_name=run.dataset_name,
        dataset_version=run.dataset_version,
        provider=run.provider,
        model=run.model,
        started_at=run.started_at,
        completed_at=run.completed_at,
        trace_id=decision.trace_id,
        aggregate_metrics=decision.aggregate_metrics,
        critical_failures=decision.critical_failures,
        framework_errors=decision.framework_errors,
        regression_summary=decision.regression_summary,
        baseline_version=decision.baseline_version,
        total_cases=total_cases,
        passed_cases=passed_cases,
        pass_rate=(passed_cases / total_cases) if total_cases else 1.0,
        total_estimated_cost=sum(c.estimated_cost for c in case_results),
        mean_latency_ms=(sum(c.latency_ms for c in case_results) / total_cases)
        if total_cases
        else 0.0,
        total_input_tokens=sum(c.input_tokens for c in case_results),
        total_output_tokens=sum(c.output_tokens for c in case_results),
        case_results=case_results,
    )
