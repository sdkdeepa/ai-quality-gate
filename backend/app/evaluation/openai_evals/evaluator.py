"""OpenAI-model-graded Evaluator implementations (Sprint 7).

Two evaluators, both `framework = "openai_evals"`, chosen after comparing
against Sprint 5's RAGAS metrics and Sprint 6's DeepEval G-Eval criteria
(see DECISIONS.md #27 for the full comparison):

- `OpenAILabelGraderEvaluator` — classifies a response into exactly one of a
  case-defined CLOSED set of labels (via Structured Outputs), and passes iff
  that label is in the case's configured passing set. Covers "policy
  compliance", "expected-behavior classification", and "engineering-domain
  quality" from the sprint brief as ONE general mechanism — all three are
  "classify into one of N discrete categories" tasks, just with different
  label sets supplied per case, so one evaluator serves all three rather
  than three near-identical ones.
- `OpenAIStructuredCorrectnessEvaluator` — checks a response against a
  CHECKLIST of independent expected facts (not a single holistic
  judgment), scoring the fraction confirmed present. Covers "structured
  answer correctness" — this is a per-fact/rubric check, structurally
  different from DeepEval's G-Eval (one holistic 0-1 score against a
  free-text rubric) or RAGAS's metrics (retrieval-grounding only).

Both are opt-in per case via `case.metadata`, same data-driven pattern as
`DeepEvalCriteriaEvaluator` (Sprint 6) and `CitationPresenceEvaluator`
(Sprint 2): a case with no relevant metadata is not applicable, not
skipped. OpenAI-specific types never appear here - only `LabelGraderResult`/
`StructuredCorrectnessResult` (success) or `OpenAIEvalsEvaluatorError`
(infrastructure failure) cross the boundary from `client.py`, and the same
`metadata["openai_evals_status"]` three-state convention Sprint 5/6
established is reused verbatim.
"""

from app.domain.evaluation_case import EvaluationCase
from app.domain.metric_result import MetricResult
from app.evaluation.openai_evals.client import OpenAIEvalsAdapter, OpenAIEvalsEvaluatorError
from app.evaluation.types import EvaluationInput

FRAMEWORK = "openai_evals"


def _skipped(metric_name: str, threshold: float, missing: list[str]) -> MetricResult:
    return MetricResult(
        metric_name=metric_name,
        score=0.0,
        threshold=threshold,
        passed=True,
        framework=FRAMEWORK,
        explanation=f"skipped: missing required input(s) for this case: {', '.join(missing)}",
        metadata={"openai_evals_status": "skipped_missing_input", "missing_inputs": missing},
    )


def _infrastructure_failure(
    metric_name: str, threshold: float, exc: OpenAIEvalsEvaluatorError
) -> MetricResult:
    return MetricResult(
        metric_name=metric_name,
        score=0.0,
        threshold=threshold,
        passed=False,
        framework=FRAMEWORK,
        explanation=(
            f"OpenAI Evals adapter infrastructure failure ({exc.error_type.value}): {exc}. "
            "This is not a quality score - the grader did not execute."
        ),
        metadata={
            "openai_evals_status": "infrastructure_error",
            "error_type": exc.error_type.value,
        },
    )


class OpenAILabelGraderEvaluator:
    """Closed-set label classification. Required per-case metadata:
    - `openai_grader_labels`: list[str] - the allowed labels (2+).
    - `openai_grader_passing_labels`: list[str] - subset of the above
      counted as passing.
    - `openai_grader_instructions`: str - the classification rubric.
    Optional: `openai_grader_name` - a short label for the metric name
    (default "label_grader").
    """

    name = "openai_evals_label_grader"
    framework = FRAMEWORK

    def __init__(self, client: OpenAIEvalsAdapter) -> None:
        self._client = client

    def applies_to(self, case: EvaluationCase) -> bool:
        return bool(
            case.metadata.get("openai_grader_labels")
            and case.metadata.get("openai_grader_passing_labels")
            and case.metadata.get("openai_grader_instructions")
        )

    def evaluate(self, evaluation_input: EvaluationInput) -> MetricResult:
        case = evaluation_input.case
        grader_name = case.metadata.get("openai_grader_name", "label_grader")
        metric_name = f"{self.name}_{grader_name}"
        labels = case.metadata.get("openai_grader_labels") or []
        passing_labels = case.metadata.get("openai_grader_passing_labels") or []
        instructions = case.metadata.get("openai_grader_instructions")

        missing = []
        if len(labels) < 2:
            missing.append("case.metadata['openai_grader_labels'] (need 2+)")
        if not passing_labels:
            missing.append("case.metadata['openai_grader_passing_labels']")
        if not instructions:
            missing.append("case.metadata['openai_grader_instructions']")
        if not evaluation_input.response.strip():
            missing.append("response")
        if missing:
            return _skipped(metric_name, 1.0, missing)

        try:
            result = self._client.classify_label(
                instructions=instructions,
                labels=labels,
                passing_labels=passing_labels,
                input_text=case.query,
                actual_output=evaluation_input.response,
            )
        except OpenAIEvalsEvaluatorError as exc:
            return _infrastructure_failure(metric_name, 1.0, exc)

        return MetricResult(
            metric_name=metric_name,
            score=1.0 if result.passed else 0.0,
            threshold=1.0,
            passed=result.passed,
            framework=FRAMEWORK,
            explanation=(
                None
                if result.passed
                else (
                    f"classified as {result.label!r} "
                    f"(not in passing set {passing_labels}): {result.reasoning}"
                )
            ),
            metadata={
                "openai_evals_status": "scored",
                "label": result.label,
                "passing_labels": passing_labels,
            },
        )


class OpenAIStructuredCorrectnessEvaluator:
    """Fact-checklist scoring. Required per-case metadata:
    - `openai_grader_expected_facts`: list[str] - independent facts/claims
      the response should correctly convey.
    Optional: `openai_grader_threshold` overrides the configured default.
    """

    name = "openai_evals_structured_correctness"
    framework = FRAMEWORK

    def __init__(self, client: OpenAIEvalsAdapter, default_threshold: float) -> None:
        self._client = client
        self._default_threshold = default_threshold

    def applies_to(self, case: EvaluationCase) -> bool:
        return bool(case.metadata.get("openai_grader_expected_facts"))

    def evaluate(self, evaluation_input: EvaluationInput) -> MetricResult:
        case = evaluation_input.case
        expected_facts = case.metadata.get("openai_grader_expected_facts") or []
        threshold = case.metadata.get("openai_grader_threshold", self._default_threshold)

        missing = []
        if not expected_facts:
            missing.append("case.metadata['openai_grader_expected_facts']")
        if not evaluation_input.response.strip():
            missing.append("response")
        if missing:
            return _skipped(self.name, threshold, missing)

        try:
            result = self._client.score_structured_facts(
                expected_facts=expected_facts,
                input_text=case.query,
                actual_output=evaluation_input.response,
            )
        except OpenAIEvalsEvaluatorError as exc:
            return _infrastructure_failure(self.name, threshold, exc)

        passed = result.score >= threshold
        return MetricResult(
            metric_name=self.name,
            score=result.score,
            threshold=threshold,
            passed=passed,
            framework=FRAMEWORK,
            explanation=None if passed else f"unsupported facts: {result.unsupported_facts}",
            metadata={
                "openai_evals_status": "scored",
                "supported_facts": result.supported_facts,
                "unsupported_facts": result.unsupported_facts,
            },
        )
