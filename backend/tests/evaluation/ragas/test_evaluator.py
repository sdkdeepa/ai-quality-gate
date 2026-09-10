from unittest.mock import MagicMock

import pytest

from app.domain.evaluation_case import EvaluationCase
from app.evaluation.ragas.client import RagasEvaluatorError, RagasScore
from app.evaluation.ragas.evaluator import (
    RagasAnswerRelevancyEvaluator,
    RagasContextPrecisionEvaluator,
    RagasContextRecallEvaluator,
    RagasFaithfulnessEvaluator,
    _is_rag_case,
)
from app.evaluation.types import EvaluationInput
from app.providers.types import ProviderErrorType


def _case(**overrides) -> EvaluationCase:
    defaults = {"id": "c1", "name": "n", "category": "rag", "query": "what is the warranty?"}
    defaults.update(overrides)
    return EvaluationCase(**defaults)


def _input(case: EvaluationCase, **overrides) -> EvaluationInput:
    defaults = {
        "case": case,
        "response": "1-year warranty.",
        "retrieved_context": ["Electronics carry a 1-year warranty."],
        "latency_ms": 500.0,
        "input_tokens": 10,
        "output_tokens": 10,
        "estimated_cost": 0.01,
    }
    defaults.update(overrides)
    return EvaluationInput(**defaults)


class TestIsRagCase:
    def test_true_for_rag_category(self):
        assert _is_rag_case(_case(category="rag")) is True

    def test_true_for_populated_reference_context(self):
        assert _is_rag_case(_case(category="answer", reference_context=["some fact"])) is True

    def test_true_for_rag_scenario_metadata(self):
        assert _is_rag_case(_case(category="answer", metadata={"rag_scenario": "correct"})) is True

    def test_false_for_a_plain_non_rag_case(self):
        assert _is_rag_case(_case(category="answer")) is False


class TestRagasFaithfulnessEvaluator:
    def test_applies_to_uses_is_rag_case(self):
        evaluator = RagasFaithfulnessEvaluator(client=MagicMock(), threshold=0.8)
        assert evaluator.applies_to(_case(category="rag")) is True
        assert evaluator.applies_to(_case(category="answer")) is False

    def test_skips_when_no_retrieved_context(self):
        evaluator = RagasFaithfulnessEvaluator(client=MagicMock(), threshold=0.8)
        case = _case()
        result = evaluator.evaluate(_input(case, retrieved_context=[]))

        assert result.passed is True
        assert result.metadata["ragas_status"] == "skipped_missing_input"
        assert "retrieved_context" in result.metadata["missing_inputs"]

    def test_skips_when_response_is_blank(self):
        evaluator = RagasFaithfulnessEvaluator(client=MagicMock(), threshold=0.8)
        case = _case()
        result = evaluator.evaluate(_input(case, response="   "))

        assert result.passed is True
        assert result.metadata["ragas_status"] == "skipped_missing_input"

    def test_passes_when_score_meets_threshold(self):
        client = MagicMock()
        client.score_faithfulness.return_value = RagasScore(value=0.95)
        evaluator = RagasFaithfulnessEvaluator(client=client, threshold=0.8)
        case = _case()

        result = evaluator.evaluate(_input(case))

        client.score_faithfulness.assert_called_once_with(
            user_input=case.query,
            response="1-year warranty.",
            retrieved_contexts=["Electronics carry a 1-year warranty."],
        )
        assert result.passed is True
        assert result.score == 0.95
        assert result.framework == "ragas"
        assert result.metric_name == "ragas_faithfulness"
        assert result.metadata["ragas_status"] == "scored"

    def test_fails_when_score_below_threshold(self):
        client = MagicMock()
        client.score_faithfulness.return_value = RagasScore(value=0.4, reason="unsupported claim")
        evaluator = RagasFaithfulnessEvaluator(client=client, threshold=0.8)

        result = evaluator.evaluate(_input(_case()))

        assert result.passed is False
        assert result.explanation == "unsupported claim"

    def test_infrastructure_failure_is_not_a_quality_score(self):
        client = MagicMock()
        client.score_faithfulness.side_effect = RagasEvaluatorError(
            "boom", error_type=ProviderErrorType.TIMEOUT
        )
        evaluator = RagasFaithfulnessEvaluator(client=client, threshold=0.8)

        result = evaluator.evaluate(_input(_case()))

        assert result.passed is False
        assert result.metadata["ragas_status"] == "infrastructure_error"
        assert result.metadata["error_type"] == "timeout"
        assert "not a quality score" in result.explanation


class TestRagasAnswerRelevancyEvaluator:
    def test_skips_when_response_blank(self):
        evaluator = RagasAnswerRelevancyEvaluator(client=MagicMock(), threshold=0.7)
        result = evaluator.evaluate(_input(_case(), response=""))
        assert result.metadata["ragas_status"] == "skipped_missing_input"

    def test_does_not_require_retrieved_context(self):
        client = MagicMock()
        client.score_answer_relevancy.return_value = RagasScore(value=0.9)
        evaluator = RagasAnswerRelevancyEvaluator(client=client, threshold=0.7)

        result = evaluator.evaluate(_input(_case(), retrieved_context=[]))

        assert result.metadata["ragas_status"] == "scored"
        assert result.passed is True


class TestRagasContextPrecisionEvaluator:
    def test_skips_when_no_expected_answer(self):
        evaluator = RagasContextPrecisionEvaluator(client=MagicMock(), threshold=0.7)
        case = _case(expected_answer=None)

        result = evaluator.evaluate(_input(case))

        assert result.passed is True
        assert result.metadata["ragas_status"] == "skipped_missing_input"
        assert any("expected_answer" in m for m in result.metadata["missing_inputs"])

    def test_skips_when_no_retrieved_context_even_with_expected_answer(self):
        evaluator = RagasContextPrecisionEvaluator(client=MagicMock(), threshold=0.7)
        case = _case(expected_answer="1-year warranty.")

        result = evaluator.evaluate(_input(case, retrieved_context=[]))

        assert result.metadata["ragas_status"] == "skipped_missing_input"
        assert "retrieved_context" in result.metadata["missing_inputs"]

    def test_scores_when_both_inputs_present(self):
        client = MagicMock()
        client.score_context_precision.return_value = RagasScore(value=0.75)
        evaluator = RagasContextPrecisionEvaluator(client=client, threshold=0.7)
        case = _case(expected_answer="1-year warranty.")

        result = evaluator.evaluate(_input(case))

        client.score_context_precision.assert_called_once_with(
            user_input=case.query,
            reference="1-year warranty.",
            retrieved_contexts=["Electronics carry a 1-year warranty."],
        )
        assert result.passed is True


class TestRagasContextRecallEvaluator:
    def test_skips_when_no_expected_answer(self):
        evaluator = RagasContextRecallEvaluator(client=MagicMock(), threshold=0.7)
        case = _case(expected_answer=None)

        result = evaluator.evaluate(_input(case))

        assert result.metadata["ragas_status"] == "skipped_missing_input"

    def test_scores_when_both_inputs_present(self):
        client = MagicMock()
        client.score_context_recall.return_value = RagasScore(value=0.6, reason="partial recall")
        evaluator = RagasContextRecallEvaluator(client=client, threshold=0.7)
        case = _case(expected_answer="1-year warranty.")

        result = evaluator.evaluate(_input(case))

        client.score_context_recall.assert_called_once_with(
            user_input=case.query,
            reference="1-year warranty.",
            retrieved_contexts=["Electronics carry a 1-year warranty."],
        )
        assert result.passed is False
        assert result.explanation == "partial recall"


@pytest.mark.parametrize(
    "evaluator_cls",
    [
        RagasFaithfulnessEvaluator,
        RagasAnswerRelevancyEvaluator,
        RagasContextPrecisionEvaluator,
        RagasContextRecallEvaluator,
    ],
)
def test_every_ragas_evaluator_never_applies_to_a_non_rag_case(evaluator_cls):
    evaluator = evaluator_cls(client=MagicMock(), threshold=0.7)
    assert evaluator.applies_to(_case(category="answer")) is False
