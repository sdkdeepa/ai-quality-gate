from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.domain.metric_result import MetricResult


class CaseResult(BaseModel):
    """The outcome of running one EvaluationCase through the system under test."""

    case_id: str = Field(min_length=1)
    response: str
    retrieved_context: list[str] = Field(default_factory=list)
    latency_ms: float = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    estimated_cost: float = Field(ge=0)
    metric_results: list[MetricResult] = Field(default_factory=list)
    passed: bool
    critical_failure: bool = False
    # Sprint 12: True whenever ANY metric_result carries
    # metadata["error_type"] — i.e. at least one evaluator never produced
    # a real "scored" result, whether that's a framework's own judge
    # hitting a normal infrastructure failure (Sprint 5/6/7's existing
    # convention) or this runner's own timeout/crash isolation (Sprint 12
    # - see app/evaluation/runner.py's `_isolated_failure_result`). Both
    # are the same underlying fact from a caller's point of view: this
    # case's evaluation is incomplete, not just imperfect, and `passed`
    # alone doesn't reveal that (a case with zero scored metrics still
    # vacuously "passes" if it has no REQUIRED metric missing — see
    # PolicyEngine — but a human reading results should still be able to
    # tell "every configured check ran" from "something didn't run").
    partial: bool = False
    # Normalized provider error metadata (error_type, message) when the system
    # under test could not be reached at all — set instead of running evaluators.
    error: dict[str, Any] | None = None

    @field_validator("case_id")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped
