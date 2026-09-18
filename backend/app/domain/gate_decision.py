from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from app.domain.enums import GateStatus


class RegressionSummary(BaseModel):
    """The result of comparing a run's aggregate results against a
    dataset's approved baseline (requirement #3/#4). Only present on a
    `GateDecision` when a baseline existed to compare against - its
    absence (`GateDecision.regression_summary is None`) means "no baseline
    exists yet for this dataset," not "no regression," and is never itself
    a reason to fail or pass.
    """

    baseline_version: int = Field(ge=1)
    pass_rate_delta: float
    # metric_name -> (current aggregate mean - baseline aggregate mean),
    # for every metric present in both. Positive = improved, negative =
    # regressed. Recorded for ALL such metrics, not only required ones,
    # so the audit trail shows the full picture even for metrics with no
    # policy threshold attached.
    metric_deltas: dict[str, float] = Field(default_factory=dict)
    # metric_name entries that regressed beyond max_regression_tolerance
    # this run, versus the baseline.
    new_failures: list[str] = Field(default_factory=list)
    # metric_name entries that were below the baseline's own bar (their
    # min_score, if configured) and are now at/above it this run.
    recovered_failures: list[str] = Field(default_factory=list)


class GateDecision(BaseModel):
    """The auditable release decision produced by the Quality Gate's own
    policy layer (`app/policy/engine.py`).

    This is deliberately independent of any evaluation framework:
    frameworks only ever produce MetricResult signals, never a decision -
    RAGAS, DeepEval, and the OpenAI-Evals-concept adapters have no idea
    this model exists. `PolicyEngine` is the only thing that constructs
    one, and it is the only place PASS/WARN/BLOCK is ever computed.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    policy_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)

    status: GateStatus
    reasons: list[str] = Field(default_factory=list)

    # metric_name -> mean score across every case where that metric
    # produced a real (non-skipped, non-infrastructure-failure) score.
    aggregate_metrics: dict[str, float] = Field(default_factory=dict)

    # case_id entries for every case whose `critical_failure` was True.
    critical_failures: list[str] = Field(default_factory=list)

    # metric_name -> count of MetricResults for that metric across the run
    # whose framework reported an infrastructure failure (never a quality
    # score of 0 - see Sprint 5/6/7's `metadata["error_type"]` convention).
    # Kept as its own field, separate from `aggregate_metrics` and
    # `reasons`, specifically so the audit trail can always distinguish
    # "the framework broke" from "the quality was bad" even for metrics
    # that weren't required by policy.
    framework_errors: dict[str, int] = Field(default_factory=dict)

    regression_summary: RegressionSummary | None = None
    baseline_version: int | None = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator(
        "run_id", "dataset_version", "provider", "model", "policy_id", "policy_version"
    )
    @classmethod
    def _not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped
