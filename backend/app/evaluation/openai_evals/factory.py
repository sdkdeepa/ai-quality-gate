"""Turns Settings into a list of OpenAI-Evals-concept Evaluators. Mirrors
`app/evaluation/ragas/factory.py` and `app/evaluation/deepeval/factory.py`
exactly: `main.py` calls `build_openai_evals_evaluators(settings)` once at
app startup and extends `EvaluationRunner`'s evaluator list with the
result. Same fail-fast rationale as Sprint 5/6 - see DECISIONS.md #21/#24.
"""

from app.core.config import Settings
from app.evaluation.base import Evaluator
from app.evaluation.openai_evals.client import OpenAIEvalsAdapter
from app.evaluation.openai_evals.evaluator import (
    OpenAILabelGraderEvaluator,
    OpenAIStructuredCorrectnessEvaluator,
)


class OpenAIEvalsConfigurationError(RuntimeError):
    """Raised at app-startup time when AQG_OPENAI_EVALS_ENABLED=true but
    required configuration is missing. Plain RuntimeError, not an
    `AppError` - no HTTP request exists yet at this point in `create_app()`.
    """


def build_openai_evals_evaluators(settings: Settings) -> list[Evaluator]:
    """Returns [] when disabled (the default) - no `openai` client is
    constructed at all in that case."""
    if not settings.openai_evals_enabled:
        return []

    if not settings.openai_api_key:
        raise OpenAIEvalsConfigurationError(
            "AQG_OPENAI_EVALS_ENABLED=true requires AQG_OPENAI_API_KEY - this "
            "adapter's judge reuses the OpenAI provider's key, the same way "
            "RAGAS's and DeepEval's judges do (see PROJECT_STATE.md)."
        )

    client = OpenAIEvalsAdapter(
        api_key=settings.openai_api_key,
        judge_model=settings.openai_evals_llm_model or settings.openai_model,
        timeout_seconds=settings.provider_timeout_seconds,
    )

    return [
        OpenAILabelGraderEvaluator(client),
        OpenAIStructuredCorrectnessEvaluator(
            client, settings.openai_evals_structured_correctness_threshold
        ),
    ]
