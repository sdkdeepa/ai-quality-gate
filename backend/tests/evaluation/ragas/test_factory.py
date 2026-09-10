import pytest

from app.core.config import Settings
from app.evaluation.ragas.evaluator import (
    RagasAnswerRelevancyEvaluator,
    RagasContextPrecisionEvaluator,
    RagasContextRecallEvaluator,
    RagasFaithfulnessEvaluator,
)
from app.evaluation.ragas.factory import RagasConfigurationError, build_ragas_evaluators


class TestRagasDisabled:
    def test_returns_empty_list_when_disabled_by_default(self):
        assert build_ragas_evaluators(Settings()) == []

    def test_returns_empty_list_even_with_no_openai_key_when_disabled(self):
        settings = Settings(ragas_enabled=False, openai_api_key=None)
        assert build_ragas_evaluators(settings) == []


class TestRagasEnabledConfigurationErrors:
    def test_raises_when_enabled_without_openai_api_key(self):
        settings = Settings(ragas_enabled=True, openai_api_key=None)

        with pytest.raises(RagasConfigurationError):
            build_ragas_evaluators(settings)

    def test_raises_on_unknown_metric_name(self):
        settings = Settings(
            ragas_enabled=True,
            openai_api_key="sk-test",
            ragas_metrics="faithfulness,not_a_real_metric",
        )

        with pytest.raises(RagasConfigurationError):
            build_ragas_evaluators(settings)


class TestRagasEnabledBuildsEvaluators:
    def test_builds_all_four_metrics_by_default(self):
        settings = Settings(ragas_enabled=True, openai_api_key="sk-test")

        evaluators = build_ragas_evaluators(settings)

        types = {type(e) for e in evaluators}
        assert types == {
            RagasFaithfulnessEvaluator,
            RagasAnswerRelevancyEvaluator,
            RagasContextPrecisionEvaluator,
            RagasContextRecallEvaluator,
        }

    def test_selected_metrics_configuration_builds_only_those(self):
        settings = Settings(
            ragas_enabled=True,
            openai_api_key="sk-test",
            ragas_metrics="faithfulness, context_recall",
        )

        evaluators = build_ragas_evaluators(settings)

        types = {type(e) for e in evaluators}
        assert types == {RagasFaithfulnessEvaluator, RagasContextRecallEvaluator}

    def test_thresholds_are_applied_from_settings(self):
        settings = Settings(
            ragas_enabled=True,
            openai_api_key="sk-test",
            ragas_metrics="faithfulness",
            ragas_faithfulness_threshold=0.55,
        )

        [evaluator] = build_ragas_evaluators(settings)

        assert evaluator._threshold == 0.55

    def test_ragas_llm_model_falls_back_to_openai_model_when_unset(self):
        # No exception constructing the client is itself the assertion here -
        # RagasClient.__init__ never makes a network call, so this proves the
        # judge_model fallback resolves without needing a real API key/network.
        settings = Settings(
            ragas_enabled=True,
            openai_api_key="sk-test",
            openai_model="gpt-4o-mini",
            ragas_llm_model=None,
        )

        evaluators = build_ragas_evaluators(settings)

        assert len(evaluators) == 4
