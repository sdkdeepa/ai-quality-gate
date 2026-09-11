from unittest.mock import MagicMock

from app.domain.evaluation_case import EvaluationCase
from app.evaluation.deepeval.client import DeepEvalEvaluatorError, DeepEvalScore
from app.evaluation.deepeval.evaluator import DeepEvalCriteriaEvaluator
from app.evaluation.types import EvaluationInput
from app.providers.types import ProviderErrorType


def _case(**overrides) -> EvaluationCase:
    defaults = {
        "id": "c1",
        "name": "n",
        "category": "answer",
        "query": "How do I return an item?",
        "metadata": {"deepeval_criteria": "Is the response empathetic and professional?"},
    }
    defaults.update(overrides)
    return EvaluationCase(**defaults)


def _input(case: EvaluationCase, **overrides) -> EvaluationInput:
    defaults = {
        "case": case,
        "response": "I'm sorry for the trouble - here's how to start a return.",
        "retrieved_context": [],
        "latency_ms": 500.0,
        "input_tokens": 10,
        "output_tokens": 10,
        "estimated_cost": 0.01,
    }
    defaults.update(overrides)
    return EvaluationInput(**defaults)


class TestAppliesTo:
    def test_true_when_criteria_metadata_present(self):
        evaluator = DeepEvalCriteriaEvaluator(client=MagicMock(), default_threshold=0.7)
        assert evaluator.applies_to(_case()) is True

    def test_false_when_no_criteria_metadata(self):
        evaluator = DeepEvalCriteriaEvaluator(client=MagicMock(), default_threshold=0.7)
        case = _case(metadata={})
        assert evaluator.applies_to(case) is False

    def test_false_for_blank_criteria_string(self):
        evaluator = DeepEvalCriteriaEvaluator(client=MagicMock(), default_threshold=0.7)
        case = _case(metadata={"deepeval_criteria": ""})
        assert evaluator.applies_to(case) is False


class TestSkipping:
    def test_skips_when_response_is_blank(self):
        evaluator = DeepEvalCriteriaEvaluator(client=MagicMock(), default_threshold=0.7)
        result = evaluator.evaluate(_input(_case(), response="   "))

        assert result.passed is True
        assert result.metadata["deepeval_status"] == "skipped_missing_input"
        assert "response" in result.metadata["missing_inputs"]


class TestScoring:
    def test_passes_when_score_meets_threshold(self):
        client = MagicMock()
        client.score_criteria.return_value = DeepEvalScore(value=0.9)
        evaluator = DeepEvalCriteriaEvaluator(client=client, default_threshold=0.7)
        case = _case()

        result = evaluator.evaluate(_input(case))

        client.score_criteria.assert_called_once_with(
            name="criteria",
            criteria="Is the response empathetic and professional?",
            threshold=0.7,
            input_text=case.query,
            actual_output="I'm sorry for the trouble - here's how to start a return.",
            expected_output=None,
            context=None,
            retrieval_context=None,
        )
        assert result.passed is True
        assert result.score == 0.9
        assert result.framework == "deepeval"
        assert result.metric_name == "deepeval_criteria"
        assert result.metadata["deepeval_status"] == "scored"

    def test_fails_when_score_below_threshold(self):
        client = MagicMock()
        client.score_criteria.return_value = DeepEvalScore(value=0.3, reason="tone was curt")
        evaluator = DeepEvalCriteriaEvaluator(client=client, default_threshold=0.7)

        result = evaluator.evaluate(_input(_case()))

        assert result.passed is False
        assert result.explanation == "tone was curt"

    def test_passes_optional_fields_through_when_present(self):
        client = MagicMock()
        client.score_criteria.return_value = DeepEvalScore(value=0.9)
        evaluator = DeepEvalCriteriaEvaluator(client=client, default_threshold=0.7)
        case = _case(
            expected_answer="a full refund within 30 days",
            reference_context=["Returns are accepted within 30 days."],
        )

        evaluator.evaluate(_input(case, retrieved_context=["chunk about returns"]))

        client.score_criteria.assert_called_once_with(
            name="criteria",
            criteria="Is the response empathetic and professional?",
            threshold=0.7,
            input_text=case.query,
            actual_output="I'm sorry for the trouble - here's how to start a return.",
            expected_output="a full refund within 30 days",
            context=["Returns are accepted within 30 days."],
            retrieval_context=["chunk about returns"],
        )

    def test_per_case_threshold_override(self):
        client = MagicMock()
        client.score_criteria.return_value = DeepEvalScore(value=0.6)
        evaluator = DeepEvalCriteriaEvaluator(client=client, default_threshold=0.7)
        case = _case(
            metadata={
                "deepeval_criteria": "Is it polite?",
                "deepeval_threshold": 0.5,
            }
        )

        result = evaluator.evaluate(_input(case))

        assert result.threshold == 0.5
        assert result.passed is True
        client.score_criteria.assert_called_once_with(
            name="criteria",
            criteria="Is it polite?",
            threshold=0.5,
            input_text=case.query,
            actual_output="I'm sorry for the trouble - here's how to start a return.",
            expected_output=None,
            context=None,
            retrieval_context=None,
        )

    def test_per_case_criteria_name_used_in_metric_name(self):
        client = MagicMock()
        client.score_criteria.return_value = DeepEvalScore(value=0.9)
        evaluator = DeepEvalCriteriaEvaluator(client=client, default_threshold=0.7)
        case = _case(
            metadata={
                "deepeval_criteria": "Is it polite?",
                "deepeval_criteria_name": "politeness",
            }
        )

        result = evaluator.evaluate(_input(case))

        assert result.metric_name == "deepeval_politeness"


class TestInfrastructureFailure:
    def test_infrastructure_failure_is_not_a_quality_score(self):
        client = MagicMock()
        client.score_criteria.side_effect = DeepEvalEvaluatorError(
            "boom", error_type=ProviderErrorType.RATE_LIMIT
        )
        evaluator = DeepEvalCriteriaEvaluator(client=client, default_threshold=0.7)

        result = evaluator.evaluate(_input(_case()))

        assert result.passed is False
        assert result.metadata["deepeval_status"] == "infrastructure_error"
        assert result.metadata["error_type"] == "rate_limit"
        assert "not a quality score" in result.explanation


def test_never_applies_to_a_case_without_deepeval_criteria_metadata():
    evaluator = DeepEvalCriteriaEvaluator(client=MagicMock(), default_threshold=0.7)
    assert evaluator.applies_to(_case(metadata={"unrelated": "x"})) is False
