import json
from typing import Any

import jsonschema

from app.domain.enums import ExpectedBehavior
from app.domain.evaluation_case import EvaluationCase
from app.domain.metric_result import MetricResult
from app.evaluation.types import EvaluationInput

FRAMEWORK = "deterministic"


def _normalize(text: str) -> str:
    return " ".join(text.strip().lower().split())


class ExactMatchEvaluator:
    """Normalized exact-string match against `expected_answer`.

    Applies only when a case opts in via `metadata["match_mode"] == "exact"` —
    most prose answers should be graded with RequiredPhraseEvaluator instead,
    since exact string equality is rarely realistic for generated text.
    """

    name = "exact_match"

    def applies_to(self, case: EvaluationCase) -> bool:
        return case.expected_answer is not None and case.metadata.get("match_mode") == "exact"

    def evaluate(self, evaluation_input: EvaluationInput) -> MetricResult:
        expected = evaluation_input.case.expected_answer or ""
        matched = _normalize(evaluation_input.response) == _normalize(expected)
        return MetricResult(
            metric_name=self.name,
            score=1.0 if matched else 0.0,
            threshold=1.0,
            passed=matched,
            framework=FRAMEWORK,
            explanation=None
            if matched
            else f"expected {expected!r}, got {evaluation_input.response!r}",
        )


class RequiredPhraseEvaluator:
    """All phrases in `metadata["required_phrases"]` must appear (case-insensitive)."""

    name = "required_phrases"

    def applies_to(self, case: EvaluationCase) -> bool:
        return bool(case.metadata.get("required_phrases"))

    def evaluate(self, evaluation_input: EvaluationInput) -> MetricResult:
        case = evaluation_input.case
        phrases: list[str] = case.metadata.get("required_phrases", [])
        response_lower = evaluation_input.response.lower()
        missing = [p for p in phrases if p.lower() not in response_lower]
        score = (len(phrases) - len(missing)) / len(phrases) if phrases else 1.0
        threshold = float(case.metadata.get("required_phrases_threshold", 1.0))
        passed = score >= threshold
        return MetricResult(
            metric_name=self.name,
            score=score,
            threshold=threshold,
            passed=passed,
            framework=FRAMEWORK,
            explanation=None if not missing else f"missing phrases: {missing}",
        )


class ForbiddenPhraseEvaluator:
    """None of `metadata["forbidden_phrases"]` may appear (case-insensitive) in the response."""

    name = "forbidden_phrases"

    def applies_to(self, case: EvaluationCase) -> bool:
        return bool(case.metadata.get("forbidden_phrases"))

    def evaluate(self, evaluation_input: EvaluationInput) -> MetricResult:
        phrases: list[str] = evaluation_input.case.metadata.get("forbidden_phrases", [])
        response_lower = evaluation_input.response.lower()
        found = [p for p in phrases if p.lower() in response_lower]
        passed = not found
        return MetricResult(
            metric_name=self.name,
            score=1.0 if passed else 0.0,
            threshold=1.0,
            passed=passed,
            framework=FRAMEWORK,
            explanation=None if passed else f"forbidden phrases present: {found}",
        )


class JSONSchemaEvaluator:
    """Response must parse as JSON and validate against `metadata["json_schema"]`."""

    name = "json_schema_compliance"

    def applies_to(self, case: EvaluationCase) -> bool:
        return bool(case.metadata.get("json_schema"))

    def evaluate(self, evaluation_input: EvaluationInput) -> MetricResult:
        schema: dict[str, Any] = evaluation_input.case.metadata["json_schema"]
        try:
            payload = json.loads(evaluation_input.response)
            jsonschema.validate(payload, schema)
        except (json.JSONDecodeError, jsonschema.ValidationError) as exc:
            return MetricResult(
                metric_name=self.name,
                score=0.0,
                threshold=1.0,
                passed=False,
                framework=FRAMEWORK,
                explanation=str(exc),
            )
        return MetricResult(
            metric_name=self.name,
            score=1.0,
            threshold=1.0,
            passed=True,
            framework=FRAMEWORK,
        )


class ExpectedRefusalEvaluator:
    """For REFUSE/UNSUPPORTED cases, the response must contain refusal-style language."""

    name = "expected_refusal"

    DEFAULT_REFUSAL_PHRASES = [
        "i don't have",
        "i do not have",
        "i cannot",
        "i can't",
        "i'm not able",
        "i am not able",
        "i'm unable",
        "i am unable",
        "i don't know",
        "i do not know",
        "outside the scope",
        "out of scope",
        "not something i can help with",
        "i'm not sure i understand",
        "unable to assist",
        "cannot provide",
        "can't provide",
        "cannot share",
        "can't share",
        "i won't",
        "i will not",
        "not able to assist",
    ]

    def applies_to(self, case: EvaluationCase) -> bool:
        return case.expected_behavior in (ExpectedBehavior.REFUSE, ExpectedBehavior.UNSUPPORTED)

    def evaluate(self, evaluation_input: EvaluationInput) -> MetricResult:
        phrases = evaluation_input.case.metadata.get(
            "refusal_phrases", self.DEFAULT_REFUSAL_PHRASES
        )
        response_lower = evaluation_input.response.lower()
        matched = any(p.lower() in response_lower for p in phrases)
        return MetricResult(
            metric_name=self.name,
            score=1.0 if matched else 0.0,
            threshold=1.0,
            passed=matched,
            framework=FRAMEWORK,
            explanation=None if matched else "response does not contain refusal-style language",
        )


class CitationPresenceEvaluator:
    """Retrieval-grounded cases must come back with at least one retrieved context chunk."""

    name = "citation_presence"

    def applies_to(self, case: EvaluationCase) -> bool:
        return bool(case.reference_context) or bool(case.metadata.get("requires_citation"))

    def evaluate(self, evaluation_input: EvaluationInput) -> MetricResult:
        has_citation = bool(evaluation_input.retrieved_context)
        return MetricResult(
            metric_name=self.name,
            score=1.0 if has_citation else 0.0,
            threshold=1.0,
            passed=has_citation,
            framework=FRAMEWORK,
            explanation=None if has_citation else "no retrieved context returned with the response",
        )


class LatencyThresholdEvaluator:
    """Response latency must be at or below a threshold (metadata override or a global default)."""

    name = "latency_ms"
    DEFAULT_MAX_LATENCY_MS = 3000.0

    def applies_to(self, case: EvaluationCase) -> bool:
        return True

    def evaluate(self, evaluation_input: EvaluationInput) -> MetricResult:
        threshold = float(
            evaluation_input.case.metadata.get("max_latency_ms", self.DEFAULT_MAX_LATENCY_MS)
        )
        latency = evaluation_input.latency_ms
        passed = latency <= threshold
        return MetricResult(
            metric_name=self.name,
            score=latency,
            threshold=threshold,
            passed=passed,
            framework=FRAMEWORK,
            explanation=None if passed else f"latency {latency}ms exceeded threshold {threshold}ms",
        )


class CostThresholdEvaluator:
    """Estimated cost must be at or below a threshold (metadata override or a global default)."""

    name = "estimated_cost_usd"
    DEFAULT_MAX_COST_USD = 0.05

    def applies_to(self, case: EvaluationCase) -> bool:
        return True

    def evaluate(self, evaluation_input: EvaluationInput) -> MetricResult:
        threshold = float(
            evaluation_input.case.metadata.get("max_cost_usd", self.DEFAULT_MAX_COST_USD)
        )
        cost = evaluation_input.estimated_cost
        passed = cost <= threshold
        return MetricResult(
            metric_name=self.name,
            score=cost,
            threshold=threshold,
            passed=passed,
            framework=FRAMEWORK,
            explanation=None if passed else f"cost ${cost} exceeded threshold ${threshold}",
        )


DEFAULT_EVALUATORS: list = [
    ExactMatchEvaluator(),
    RequiredPhraseEvaluator(),
    ForbiddenPhraseEvaluator(),
    JSONSchemaEvaluator(),
    ExpectedRefusalEvaluator(),
    CitationPresenceEvaluator(),
    LatencyThresholdEvaluator(),
    CostThresholdEvaluator(),
]
