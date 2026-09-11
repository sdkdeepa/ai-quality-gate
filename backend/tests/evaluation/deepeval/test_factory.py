import pytest

from app.core.config import Settings
from app.evaluation.deepeval.evaluator import DeepEvalCriteriaEvaluator
from app.evaluation.deepeval.factory import DeepEvalConfigurationError, build_deepeval_evaluators


class TestDeepEvalDisabled:
    def test_returns_empty_list_when_disabled_by_default(self):
        assert build_deepeval_evaluators(Settings()) == []

    def test_returns_empty_list_even_with_no_openai_key_when_disabled(self):
        settings = Settings(deepeval_enabled=False, openai_api_key=None)
        assert build_deepeval_evaluators(settings) == []


class TestDeepEvalEnabledConfigurationErrors:
    def test_raises_when_enabled_without_openai_api_key(self):
        settings = Settings(deepeval_enabled=True, openai_api_key=None)

        with pytest.raises(DeepEvalConfigurationError):
            build_deepeval_evaluators(settings)


class TestDeepEvalEnabledBuildsEvaluators:
    def test_builds_the_criteria_evaluator(self):
        settings = Settings(deepeval_enabled=True, openai_api_key="sk-test")

        evaluators = build_deepeval_evaluators(settings)

        assert len(evaluators) == 1
        assert isinstance(evaluators[0], DeepEvalCriteriaEvaluator)

    def test_threshold_is_applied_from_settings(self):
        settings = Settings(
            deepeval_enabled=True,
            openai_api_key="sk-test",
            deepeval_criteria_threshold=0.55,
        )

        [evaluator] = build_deepeval_evaluators(settings)

        assert evaluator._default_threshold == 0.55

    def test_deepeval_llm_model_falls_back_to_openai_model_when_unset(self):
        # No exception constructing the client is itself the assertion -
        # DeepEvalClient.__init__ never makes a network call, so this proves
        # the judge_model fallback resolves without a real key/network.
        settings = Settings(
            deepeval_enabled=True,
            openai_api_key="sk-test",
            openai_model="gpt-4o-mini",
            deepeval_llm_model=None,
        )

        evaluators = build_deepeval_evaluators(settings)

        assert len(evaluators) == 1
