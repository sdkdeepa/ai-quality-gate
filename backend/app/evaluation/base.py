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
    # Sprint 6: which framework this evaluator's MetricResults are tagged
    # with ("deterministic" / "ragas" / "deepeval" / ...). Added so
    # EvaluationRunner can filter its evaluator list by framework
    # (requirement: API-based evaluator-combination selection) without
    # having to run an evaluator just to find out what it is. Every
    # MetricResult already carried this; it was only missing on the
    # Evaluator itself.
    framework: str

    def applies_to(self, case: EvaluationCase) -> bool:
        """Whether this evaluator has anything to check for the given case."""
        ...

    def evaluate(self, evaluation_input: EvaluationInput) -> MetricResult: ...
