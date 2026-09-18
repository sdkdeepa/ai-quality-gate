from unittest.mock import MagicMock

from app.domain.evaluation_case import EvaluationCase
from app.evaluation.openai_evals.client import (
    LabelGraderResult,
    OpenAIEvalsEvaluatorError,
    StructuredCorrectnessResult,
)
from app.evaluation.openai_evals.evaluator import (
    OpenAILabelGraderEvaluator,
    OpenAIStructuredCorrectnessEvaluator,
)
from app.evaluation.types import EvaluationInput
from app.providers.types import ProviderErrorType


def _case(**overrides) -> EvaluationCase:
    defaults = {
        "id": "c1",
        "name": "n",
        "category": "answer",
        "query": "My package was late, what's your policy?",
        "metadata": {
            "openai_grader_labels": ["compliant", "non_compliant"],
            "openai_grader_passing_labels": ["compliant"],
            "openai_grader_instructions": "Does the response comply with the late-delivery policy?",
        },
    }
    defaults.update(overrides)
    return EvaluationCase(**defaults)


def _input(case: EvaluationCase, **overrides) -> EvaluationInput:
    defaults = {
        "case": case,
        "response": "We're sorry for the delay - here's a partial refund per policy.",
        "retrieved_context": [],
        "latency_ms": 500.0,
        "input_tokens": 10,
        "output_tokens": 10,
        "estimated_cost": 0.01,
    }
    defaults.update(overrides)
    return EvaluationInput(**defaults)


class TestOpenAILabelGraderApplies:
    def test_true_when_all_required_metadata_present(self):
        evaluator = OpenAILabelGraderEvaluator(client=MagicMock())
        assert evaluator.applies_to(_case()) is True

    def test_false_when_metadata_absent(self):
        evaluator = OpenAILabelGraderEvaluator(client=MagicMock())
        assert evaluator.applies_to(_case(metadata={})) is False

    def test_false_when_only_labels_present(self):
        evaluator = OpenAILabelGraderEvaluator(client=MagicMock())
        case = _case(metadata={"openai_grader_labels": ["a", "b"]})
        assert evaluator.applies_to(case) is False


class TestOpenAILabelGraderSkipping:
    def test_skips_with_fewer_than_two_labels(self):
        evaluator = OpenAILabelGraderEvaluator(client=MagicMock())
        case = _case(
            metadata={
                "openai_grader_labels": ["only_one"],
                "openai_grader_passing_labels": ["only_one"],
                "openai_grader_instructions": "x",
            }
        )
        # applies_to is False too (needs 2+ practically) but evaluate()'s own
        # check is exercised directly here for defense-in-depth.
        result = evaluator.evaluate(_input(case))
        assert result.metadata["openai_evals_status"] == "skipped_missing_input"

    def test_skips_when_response_blank(self):
        evaluator = OpenAILabelGraderEvaluator(client=MagicMock())
        result = evaluator.evaluate(_input(_case(), response="   "))
        assert result.metadata["openai_evals_status"] == "skipped_missing_input"
        assert "response" in result.metadata["missing_inputs"]


class TestOpenAILabelGraderScoring:
    def test_passes_when_label_in_passing_set(self):
        client = MagicMock()
        client.classify_label.return_value = LabelGraderResult(
            label="compliant", passed=True, reasoning="matches policy"
        )
        evaluator = OpenAILabelGraderEvaluator(client=client)
        case = _case()

        result = evaluator.evaluate(_input(case))

        client.classify_label.assert_called_once_with(
            instructions="Does the response comply with the late-delivery policy?",
            labels=["compliant", "non_compliant"],
            passing_labels=["compliant"],
            input_text=case.query,
            actual_output="We're sorry for the delay - here's a partial refund per policy.",
        )
        assert result.passed is True
        assert result.score == 1.0
        assert result.framework == "openai_evals"
        assert result.metric_name == "openai_evals_label_grader_label_grader"
        assert result.metadata["openai_evals_status"] == "scored"
        assert result.metadata["label"] == "compliant"

    def test_fails_when_label_not_in_passing_set(self):
        client = MagicMock()
        client.classify_label.return_value = LabelGraderResult(
            label="non_compliant", passed=False, reasoning="offers no remedy"
        )
        evaluator = OpenAILabelGraderEvaluator(client=client)

        result = evaluator.evaluate(_input(_case()))

        assert result.passed is False
        assert result.score == 0.0
        assert "non_compliant" in result.explanation

    def test_custom_grader_name_used_in_metric_name(self):
        client = MagicMock()
        client.classify_label.return_value = LabelGraderResult(label="a", passed=True)
        evaluator = OpenAILabelGraderEvaluator(client=client)
        case = _case(
            metadata={
                "openai_grader_labels": ["a", "b"],
                "openai_grader_passing_labels": ["a"],
                "openai_grader_instructions": "x",
                "openai_grader_name": "engineering_quality",
            }
        )

        result = evaluator.evaluate(_input(case))

        assert result.metric_name == "openai_evals_label_grader_engineering_quality"

    def test_infrastructure_failure_is_not_a_quality_score(self):
        client = MagicMock()
        client.classify_label.side_effect = OpenAIEvalsEvaluatorError(
            "boom", error_type=ProviderErrorType.AUTHENTICATION
        )
        evaluator = OpenAILabelGraderEvaluator(client=client)

        result = evaluator.evaluate(_input(_case()))

        assert result.passed is False
        assert result.metadata["openai_evals_status"] == "infrastructure_error"
        assert result.metadata["error_type"] == "authentication"
        assert "not a quality score" in result.explanation


def _structured_case(**overrides) -> EvaluationCase:
    defaults = {
        "id": "c2",
        "name": "n",
        "category": "answer",
        "query": "What's the return policy?",
        "metadata": {
            "openai_grader_expected_facts": ["30-day return window", "free return shipping"]
        },
    }
    defaults.update(overrides)
    return EvaluationCase(**defaults)


class TestOpenAIStructuredCorrectnessApplies:
    def test_true_when_expected_facts_present(self):
        evaluator = OpenAIStructuredCorrectnessEvaluator(client=MagicMock(), default_threshold=0.8)
        assert evaluator.applies_to(_structured_case()) is True

    def test_false_when_no_expected_facts(self):
        evaluator = OpenAIStructuredCorrectnessEvaluator(client=MagicMock(), default_threshold=0.8)
        assert evaluator.applies_to(_structured_case(metadata={})) is False


class TestOpenAIStructuredCorrectnessScoring:
    def test_passes_when_score_meets_threshold(self):
        client = MagicMock()
        client.score_structured_facts.return_value = StructuredCorrectnessResult(
            score=0.9, supported_facts=["30-day return window"], unsupported_facts=[]
        )
        evaluator = OpenAIStructuredCorrectnessEvaluator(client=client, default_threshold=0.8)
        case = _structured_case()

        result = evaluator.evaluate(_input(case, response="Returns within 30 days, free shipping."))

        client.score_structured_facts.assert_called_once_with(
            expected_facts=["30-day return window", "free return shipping"],
            input_text=case.query,
            actual_output="Returns within 30 days, free shipping.",
        )
        assert result.passed is True
        assert result.score == 0.9
        assert result.metadata["openai_evals_status"] == "scored"

    def test_fails_when_score_below_threshold(self):
        client = MagicMock()
        client.score_structured_facts.return_value = StructuredCorrectnessResult(
            score=0.5,
            supported_facts=["30-day return window"],
            unsupported_facts=["free return shipping"],
        )
        evaluator = OpenAIStructuredCorrectnessEvaluator(client=client, default_threshold=0.8)

        result = evaluator.evaluate(_input(_structured_case()))

        assert result.passed is False
        assert "free return shipping" in result.explanation

    def test_per_case_threshold_override(self):
        client = MagicMock()
        client.score_structured_facts.return_value = StructuredCorrectnessResult(
            score=0.5, supported_facts=[], unsupported_facts=[]
        )
        evaluator = OpenAIStructuredCorrectnessEvaluator(client=client, default_threshold=0.8)
        case = _structured_case(
            metadata={
                "openai_grader_expected_facts": ["fact1"],
                "openai_grader_threshold": 0.4,
            }
        )

        result = evaluator.evaluate(_input(case))

        assert result.threshold == 0.4
        assert result.passed is True

    def test_infrastructure_failure_is_not_a_quality_score(self):
        client = MagicMock()
        client.score_structured_facts.side_effect = OpenAIEvalsEvaluatorError(
            "boom", error_type=ProviderErrorType.RATE_LIMIT
        )
        evaluator = OpenAIStructuredCorrectnessEvaluator(client=client, default_threshold=0.8)

        result = evaluator.evaluate(_input(_structured_case()))

        assert result.passed is False
        assert result.metadata["openai_evals_status"] == "infrastructure_error"
        assert result.metadata["error_type"] == "rate_limit"
