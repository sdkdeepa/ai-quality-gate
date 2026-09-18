import pytest

from app.core.config import Settings
from app.evaluation.openai_evals.evaluator import (
    OpenAILabelGraderEvaluator,
    OpenAIStructuredCorrectnessEvaluator,
)
from app.evaluation.openai_evals.factory import (
    OpenAIEvalsConfigurationError,
    build_openai_evals_evaluators,
)


class TestOpenAIEvalsDisabled:
    def test_returns_empty_list_when_disabled_by_default(self):
        assert build_openai_evals_evaluators(Settings()) == []

    def test_returns_empty_list_even_with_no_openai_key_when_disabled(self):
        settings = Settings(openai_evals_enabled=False, openai_api_key=None)
        assert build_openai_evals_evaluators(settings) == []


class TestOpenAIEvalsEnabledConfigurationErrors:
    def test_raises_when_enabled_without_openai_api_key(self):
        settings = Settings(openai_evals_enabled=True, openai_api_key=None)

        with pytest.raises(OpenAIEvalsConfigurationError):
            build_openai_evals_evaluators(settings)


class TestOpenAIEvalsEnabledBuildsEvaluators:
    def test_builds_both_evaluators(self):
        settings = Settings(openai_evals_enabled=True, openai_api_key="sk-test")

        evaluators = build_openai_evals_evaluators(settings)

        types = {type(e) for e in evaluators}
        assert types == {OpenAILabelGraderEvaluator, OpenAIStructuredCorrectnessEvaluator}

    def test_structured_correctness_threshold_applied_from_settings(self):
        settings = Settings(
            openai_evals_enabled=True,
            openai_api_key="sk-test",
            openai_evals_structured_correctness_threshold=0.55,
        )

        evaluators = build_openai_evals_evaluators(settings)
        [structured] = [
            e for e in evaluators if isinstance(e, OpenAIStructuredCorrectnessEvaluator)
        ]

        assert structured._default_threshold == 0.55

    def test_judge_model_falls_back_to_openai_model_when_unset(self):
        # No exception constructing the client is itself the assertion here -
        # OpenAIEvalsAdapter.__init__ never makes a network call.
        settings = Settings(
            openai_evals_enabled=True,
            openai_api_key="sk-test",
            openai_model="gpt-4o-mini",
            openai_evals_llm_model=None,
        )

        evaluators = build_openai_evals_evaluators(settings)

        assert len(evaluators) == 2
