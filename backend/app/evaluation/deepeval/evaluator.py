"""DeepEval-backed Evaluator implementation.

Sprint 6 ships exactly one DeepEval evaluator — `DeepEvalCriteriaEvaluator`,
a configurable G-Eval custom-criteria check — after comparing all four
"potential areas" the sprint brief listed (answer relevancy, faithfulness/
groundedness, hallucination, custom expected-behavior criteria) against
what Sprint 5's RAGAS evaluators and Sprint 1-4's deterministic evaluators
already cover. See DECISIONS.md #23 for the full comparison; the short
version: DeepEval's AnswerRelevancyMetric and FaithfulnessMetric measure the
same thing as RAGAS's AnswerRelevancy/Faithfulness (Sprint 5) on the same
case population, and DeepEval's HallucinationMetric measures materially the
same claim-grounding question as RAGAS's Faithfulness once you strip away
each library's own framing — none of the three add enough unique signal to
justify a second framework's opinion on an identical question. Custom
expected-behavior criteria via G-Eval is the one capability nothing else in
the Gate provides at all: every deterministic evaluator only does literal
string/schema matching, and RAGAS's four metrics are all retrieval-grounding
questions. G-Eval is the first *qualitative/semantic* judge in the Gate
(tone, professionalism, policy adherence, or any other natural-language
rubric a dataset author writes into `case.metadata["deepeval_criteria"]`).

Implements the same `Evaluator` protocol (`app/evaluation/base.py`) as the
deterministic and RAGAS evaluators — `applies_to(case) -> bool` and
`evaluate(input) -> MetricResult`, plus the `framework` attribute Sprint 6
added to the protocol for evaluator-combination selection
(`app/evaluation/runner.py`). DeepEval-specific types never appear here —
only `DeepEvalScore` (success) and `DeepEvalEvaluatorError` (infrastructure
failure) cross the boundary from `client.py`, and the same three normalized
non-quality states from Sprint 5 (`scored` / `skipped_missing_input` /
`infrastructure_error`) are reused verbatim via `metadata["deepeval_status"]`.
"""

from app.domain.evaluation_case import EvaluationCase
from app.domain.metric_result import MetricResult
from app.evaluation.deepeval.client import DeepEvalClient, DeepEvalEvaluatorError
from app.evaluation.types import EvaluationInput

FRAMEWORK = "deepeval"


class DeepEvalCriteriaEvaluator:
    """Judges a response against a natural-language rubric the dataset
    author supplies per case via `case.metadata["deepeval_criteria"]" — e.g.
    "Is the response empathetic and does it avoid making promises about
    refund timing?". Opt-in and data-driven, same pattern as
    `CitationPresenceEvaluator` (Sprint 2): a case with no
    `deepeval_criteria` metadata is simply not applicable, not skipped —
    `applies_to` returns False and the evaluator is never invoked for it.

    Optional per-case overrides (all in `case.metadata`, so still
    Quality-Gate-owned data, never DeepEval's):
    - `deepeval_criteria_name`: a short label for the criterion, used as
      part of `MetricResult.metric_name` (default: "criteria").
    - `deepeval_threshold`: overrides the evaluator's configured default
      threshold for this case specifically.
    """

    name = "deepeval_criteria"
    framework = FRAMEWORK

    def __init__(self, client: DeepEvalClient, default_threshold: float) -> None:
        self._client = client
        self._default_threshold = default_threshold

    def applies_to(self, case: EvaluationCase) -> bool:
        return bool(case.metadata.get("deepeval_criteria"))

    def evaluate(self, evaluation_input: EvaluationInput) -> MetricResult:
        case = evaluation_input.case
        criteria = case.metadata.get("deepeval_criteria")
        threshold = case.metadata.get("deepeval_threshold", self._default_threshold)
        criteria_name = case.metadata.get("deepeval_criteria_name", "criteria")
        metric_name = f"deepeval_{criteria_name}"

        missing = self._missing_inputs(evaluation_input, criteria)
        if missing:
            return self._skipped(metric_name, threshold, missing)

        try:
            score = self._client.score_criteria(
                name=criteria_name,
                criteria=criteria,
                threshold=threshold,
                input_text=case.query,
                actual_output=evaluation_input.response,
                expected_output=case.expected_answer,
                context=case.reference_context or None,
                retrieval_context=evaluation_input.retrieved_context or None,
            )
        except DeepEvalEvaluatorError as exc:
            return self._infrastructure_failure(metric_name, threshold, exc)

        passed = score.value >= threshold
        return MetricResult(
            metric_name=metric_name,
            score=score.value,
            threshold=threshold,
            passed=passed,
            framework=FRAMEWORK,
            explanation=score.reason if (not passed and score.reason) else None,
            metadata={"deepeval_status": "scored", "criteria": criteria},
        )

    def _missing_inputs(self, evaluation_input: EvaluationInput, criteria: str | None) -> list[str]:
        missing = []
        if not criteria:
            missing.append("case.metadata['deepeval_criteria']")
        if not evaluation_input.response.strip():
            missing.append("response")
        return missing

    def _skipped(self, metric_name: str, threshold: float, missing: list[str]) -> MetricResult:
        return MetricResult(
            metric_name=metric_name,
            score=0.0,
            threshold=threshold,
            passed=True,
            framework=FRAMEWORK,
            explanation=f"skipped: missing required input(s) for this case: {', '.join(missing)}",
            metadata={"deepeval_status": "skipped_missing_input", "missing_inputs": missing},
        )

    def _infrastructure_failure(
        self, metric_name: str, threshold: float, exc: DeepEvalEvaluatorError
    ) -> MetricResult:
        return MetricResult(
            metric_name=metric_name,
            score=0.0,
            threshold=threshold,
            passed=False,
            framework=FRAMEWORK,
            explanation=(
                f"DeepEval evaluator infrastructure failure ({exc.error_type.value}): {exc}. "
                "This is not a quality score — the metric did not execute."
            ),
            metadata={
                "deepeval_status": "infrastructure_error",
                "error_type": exc.error_type.value,
            },
        )
