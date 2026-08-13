from typing import Protocol

from app.domain.evaluation_case import EvaluationCase
from app.domain.metric_result import MetricResult
from app.evaluation.types import EvaluationInput


class Evaluator(Protocol):
    """A single deterministic (or, later, framework-backed) scoring signal.

    Evaluators never make a release decision — they only ever produce a
    normalized MetricResult. Thresholds, policy, and PASS/WARN/BLOCK
    decisions belong to the Quality Gate, not to individual evaluators or
    the frameworks that might eventually back them.
    """

    name: str

    def applies_to(self, case: EvaluationCase) -> bool:
        """Whether this evaluator has anything to check for the given case."""
        ...

    def evaluate(self, evaluation_input: EvaluationInput) -> MetricResult: ...
