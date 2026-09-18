from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


class RequiredMetricPolicy(BaseModel):
    """One metric the release policy requires to have actually executed and
    scored, with an optional aggregate quality bar on top of whatever
    per-case threshold the evaluator itself already applies.

    `metric_name` matches `MetricResult.metric_name` exactly (e.g.
    "exact_match", "ragas_faithfulness", "deepeval_criteria",
    "openai_evals_label_grader_label_grader").
    """

    metric_name: str = Field(min_length=1)
    # Aggregate (mean, across every case in the run where this metric
    # produced a real score) quality bar. None means: don't impose an
    # additional run-level bar - rely only on each case's own `passed` flag
    # (which already reflects the evaluator's own per-case threshold).
    min_score: float | None = Field(default=None, ge=0.0, le=1.0)
    # What to do if this metric never executed anywhere in the run at all -
    # the evaluator was disabled process-wide, unavailable, or not
    # applicable to any case in the dataset. Defaults to "block": per the
    # sprint's explicit semantics, a required evaluator that never ran must
    # never be silently treated as passing.
    on_missing: Literal["block", "warn", "ignore"] = "block"
    # What to do if this metric DID execute but every attempt (or any
    # attempt - see PolicyEngine) came back as an evaluator infrastructure
    # failure rather than a real score. Kept separate from `on_missing`
    # because "never ran" and "ran but the framework/judge broke" are
    # different failure modes worth different default handling in
    # principle, even though both default to "block" here.
    on_infrastructure_failure: Literal["block", "warn", "ignore"] = "block"

    @field_validator("metric_name")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class ReleasePolicy(BaseModel):
    """The Quality Gate's own, platform-owned release policy. Nothing in
    `app/evaluation/` (deterministic, RAGAS, DeepEval, or the OpenAI-Evals-
    concept adapters) ever computes PASS/WARN/BLOCK - they only ever
    produce `MetricResult`s. This model is the only place thresholds,
    required metrics, and pass/fail policy for a *release* (as opposed to a
    single metric) are defined. See DECISIONS.md #28.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)

    required_metrics: list[RequiredMetricPolicy] = Field(default_factory=list)

    # Minimum fraction (0..1) of cases in the run that must have `passed`.
    # Always a hard BLOCK when missed - this is the headline quality bar,
    # not something a policy should be able to downgrade to a warning.
    min_pass_rate: float = Field(default=1.0, ge=0.0, le=1.0)

    # What a critical-case failure (CaseResult.critical_failure, Sprint 2)
    # causes. Configurable (unlike min_pass_rate) because some
    # organizations may want critical failures surfaced as WARN during an
    # early rollout phase rather than hard-blocking immediately - but
    # "ignore" is deliberately not offered here: a critical case existing
    # at all means someone marked it non-negotiable in the dataset, so the
    # policy must at least surface it.
    critical_case_action: Literal["block", "warn"] = "block"

    # Regression tolerance against the dataset's approved baseline (if
    # any). Expressed as an absolute drop (0..1) allowed in min_pass_rate
    # or in any required metric's aggregate mean score before it counts as
    # a regression. 0.0 means "any regression at all is flagged."
    max_regression_tolerance: float = Field(default=0.0, ge=0.0, le=1.0)
    regression_action: Literal["block", "warn"] = "block"

    # Budgets. None means "not enforced." Both default to "warn" rather
    # than "block": a slow or expensive-but-correct response is usually a
    # product/cost concern, not a correctness one, so it shouldn't block a
    # release the same way a required-metric or critical-case failure
    # does - but teams that want it to hard-block can set the action
    # explicitly.
    latency_budget_ms: float | None = Field(default=None, ge=0.0)
    latency_budget_action: Literal["block", "warn"] = "warn"
    cost_budget_usd: float | None = Field(default=None, ge=0.0)
    cost_budget_action: Literal["block", "warn"] = "warn"

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("name", "version")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


DEFAULT_POLICY_NAME = "default"
DEFAULT_POLICY_VERSION = "1.0.0"


def default_policy() -> ReleasePolicy:
    """The policy seeded at startup when none has been configured yet.

    Deliberately permissive (no required metrics, min_pass_rate=1.0 which
    only blocks on an actual case failure, no budgets) rather than
    speculatively strict - a fresh install should not immediately BLOCK
    every run on requirements nobody configured. Register a stricter
    policy via `POST /api/v1/gate/policies` once real requirements are
    known. min_pass_rate=1.0 is still meaningful even with zero configured
    required metrics: it means "every case that DID run an evaluator must
    have passed it," which is a reasonable, non-vacuous default - it is
    the zero-metrics-executed-at-all case that PolicyEngine separately
    guards against unconditionally (see DECISIONS.md #28).
    """
    return ReleasePolicy(name=DEFAULT_POLICY_NAME, version=DEFAULT_POLICY_VERSION)
