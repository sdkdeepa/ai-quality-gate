"""RAGAS-backed Evaluator implementations.

Each class here implements the same `Evaluator` protocol
(`app/evaluation/base.py`) as the deterministic evaluators in
`app/evaluation/deterministic.py` — `applies_to(case) -> bool` and
`evaluate(input) -> MetricResult`. `EvaluationRunner` treats them
identically; the only thing that differs is `framework="ragas"` on the
resulting `MetricResult` and the fact that scoring goes through
`RagasClient` instead of a pure string/schema check.

RAGAS-specific types never appear here — only `RagasScore` (a success) and
`RagasEvaluatorError` (an infrastructure failure) cross the boundary from
`client.py`. Scoring never fabricates a value for a case missing its
required inputs (`_missing_inputs` -> an explicit skipped MetricResult
instead), and an infrastructure failure is never represented as a quality
score of 0 (`_infrastructure_failure` -> an explicit failed-to-execute
MetricResult with `metadata["ragas_status"] == "infrastructure_error"`).
See DECISIONS.md #22 for why these are separate cases.
"""

from app.domain.evaluation_case import EvaluationCase
from app.domain.metric_result import MetricResult
from app.evaluation.ragas.client import RagasClient, RagasEvaluatorError, RagasScore
from app.evaluation.types import EvaluationInput

FRAMEWORK = "ragas"


def _is_rag_case(case: EvaluationCase) -> bool:
    """Coarse applicability filter — same data-driven pattern as
    `CitationPresenceEvaluator.applies_to` (Sprint 2's
    `app/evaluation/deterministic.py`), just keyed on RAG-specific signals:
    the `rag` category, a populated `reference_context`, or the
    `rag_scenario` metadata Sprint 4's dataset uses. Per-case required-input
    checks (does *this* case have a reference answer, retrieved context,
    ...) happen in `_missing_inputs`, not here — this only decides whether
    RAGAS has anything conceptually to say about the case at all.
    """
    return case.category == "rag" or bool(case.reference_context) or "rag_scenario" in case.metadata


class RagasMetricEvaluator:
    """Shared evaluate()/skip/infrastructure-failure plumbing for one RAGAS
    metric. Subclasses declare `name` and how to check/call for their metric.
    """

    name: str = "ragas_metric"

    def __init__(self, client: RagasClient, threshold: float) -> None:
        self._client = client
        self._threshold = threshold

    def applies_to(self, case: EvaluationCase) -> bool:
        return _is_rag_case(case)

    def evaluate(self, evaluation_input: EvaluationInput) -> MetricResult:
        missing = self._missing_inputs(evaluation_input)
        if missing:
            return self._skipped(missing)

        try:
            score = self._score(evaluation_input)
        except RagasEvaluatorError as exc:
            return self._infrastructure_failure(exc)

        passed = score.value >= self._threshold
        return MetricResult(
            metric_name=self.name,
            score=score.value,
            threshold=self._threshold,
            passed=passed,
            framework=FRAMEWORK,
            explanation=score.reason if (not passed and score.reason) else None,
            metadata={"ragas_status": "scored"},
        )

    # -- subclass hooks --------------------------------------------------

    def _missing_inputs(self, evaluation_input: EvaluationInput) -> list[str]:
        raise NotImplementedError

    def _score(self, evaluation_input: EvaluationInput) -> RagasScore:
        raise NotImplementedError

    # -- normalized non-quality outcomes ---------------------------------

    def _skipped(self, missing: list[str]) -> MetricResult:
        """Explicit not-applicable result for a case missing a required
        input (e.g. no reference answer). Never fabricated, never silently
        omitted, never scored — `passed=True` because "not applicable"
        must not fail a case, distinct from a real quality failure."""
        return MetricResult(
            metric_name=self.name,
            score=0.0,
            threshold=self._threshold,
            passed=True,
            framework=FRAMEWORK,
            explanation=f"skipped: missing required input(s) for this case: {', '.join(missing)}",
            metadata={"ragas_status": "skipped_missing_input", "missing_inputs": missing},
        )

    def _infrastructure_failure(self, exc: RagasEvaluatorError) -> MetricResult:
        """Explicit evaluator-infrastructure-failure result. `passed=False`
        so a RAGAS outage never silently produces PASS — but `metadata`
        distinguishes this from a real quality failure (score=0.42 vs.
        threshold=0.80) so a future Policy Engine sprint can treat it
        differently (e.g. WARN/retry) instead of a hard BLOCK."""
        return MetricResult(
            metric_name=self.name,
            score=0.0,
            threshold=self._threshold,
            passed=False,
            framework=FRAMEWORK,
            explanation=(
                f"RAGAS evaluator infrastructure failure ({exc.error_type.value}): {exc}. "
                "This is not a quality score — the metric did not execute."
            ),
            metadata={"ragas_status": "infrastructure_error", "error_type": exc.error_type.value},
        )


class RagasFaithfulnessEvaluator(RagasMetricEvaluator):
    """Are the claims in the response supported by the retrieved context?
    Needs at least one retrieved chunk and a non-empty response; no
    reference answer required."""

    name = "ragas_faithfulness"

    def _missing_inputs(self, evaluation_input: EvaluationInput) -> list[str]:
        missing = []
        if not evaluation_input.retrieved_context:
            missing.append("retrieved_context")
        if not evaluation_input.response.strip():
            missing.append("response")
        return missing

    def _score(self, evaluation_input: EvaluationInput) -> RagasScore:
        return self._client.score_faithfulness(
            user_input=evaluation_input.case.query,
            response=evaluation_input.response,
            retrieved_contexts=evaluation_input.retrieved_context,
        )


class RagasAnswerRelevancyEvaluator(RagasMetricEvaluator):
    """Does the response actually address the user's query? Needs only a
    non-empty response — no retrieved context or reference required, so
    this still runs for refusal/unsupported RAG cases."""

    name = "ragas_answer_relevancy"

    def _missing_inputs(self, evaluation_input: EvaluationInput) -> list[str]:
        return ["response"] if not evaluation_input.response.strip() else []

    def _score(self, evaluation_input: EvaluationInput) -> RagasScore:
        return self._client.score_answer_relevancy(
            user_input=evaluation_input.case.query,
            response=evaluation_input.response,
        )


class RagasContextPrecisionEvaluator(RagasMetricEvaluator):
    """Are the relevant retrieved chunks ranked ahead of irrelevant ones,
    judged against the case's reference answer? Needs both
    `case.expected_answer` and at least one retrieved chunk — the
    irrelevant/missing/unsupported RAG scenarios have neither by design
    (see `customer_support_bot.v1.1.0.json`), so this is skipped rather than
    scored for those, not fabricated."""

    name = "ragas_context_precision"

    def _missing_inputs(self, evaluation_input: EvaluationInput) -> list[str]:
        missing = []
        if not evaluation_input.case.expected_answer:
            missing.append("case.expected_answer (reference)")
        if not evaluation_input.retrieved_context:
            missing.append("retrieved_context")
        return missing

    def _score(self, evaluation_input: EvaluationInput) -> RagasScore:
        return self._client.score_context_precision(
            user_input=evaluation_input.case.query,
            reference=evaluation_input.case.expected_answer or "",
            retrieved_contexts=evaluation_input.retrieved_context,
        )


class RagasContextRecallEvaluator(RagasMetricEvaluator):
    """Does the retrieved context cover everything the reference answer
    claims? Same required-input shape as ContextPrecision, for the same
    reason."""

    name = "ragas_context_recall"

    def _missing_inputs(self, evaluation_input: EvaluationInput) -> list[str]:
        missing = []
        if not evaluation_input.case.expected_answer:
            missing.append("case.expected_answer (reference)")
        if not evaluation_input.retrieved_context:
            missing.append("retrieved_context")
        return missing

    def _score(self, evaluation_input: EvaluationInput) -> RagasScore:
        return self._client.score_context_recall(
            user_input=evaluation_input.case.query,
            reference=evaluation_input.case.expected_answer or "",
            retrieved_contexts=evaluation_input.retrieved_context,
        )
