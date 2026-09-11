"""Turns Settings into a list of DeepEval Evaluators. Mirrors
`app/evaluation/ragas/factory.py` exactly: `main.py` calls
`build_deepeval_evaluators(settings)` once at app startup and extends
`EvaluationRunner`'s evaluator list with the result. Same fail-fast
rationale as Sprint 5 — see DECISIONS.md #21 and #24.
"""

from app.core.config import Settings
from app.evaluation.base import Evaluator
from app.evaluation.deepeval.client import DeepEvalClient
from app.evaluation.deepeval.evaluator import DeepEvalCriteriaEvaluator


class DeepEvalConfigurationError(RuntimeError):
    """Raised at app-startup time when AQG_DEEPEVAL_ENABLED=true but
    required configuration is missing. Plain RuntimeError, not an
    `AppError` — no HTTP request exists yet at this point in `create_app()`.
    """


def build_deepeval_evaluators(settings: Settings) -> list[Evaluator]:
    """Returns [] when DeepEval is disabled (the default) — no `deepeval`/
    `openai` judge-client objects are constructed at all in that case."""
    if not settings.deepeval_enabled:
        return []

    if not settings.openai_api_key:
        raise DeepEvalConfigurationError(
            "AQG_DEEPEVAL_ENABLED=true requires AQG_OPENAI_API_KEY — DeepEval's "
            "G-Eval judge currently reuses the OpenAI provider's key, the same "
            "way RAGAS's judge does (see PROJECT_STATE.md)."
        )

    client = DeepEvalClient(
        api_key=settings.openai_api_key,
        judge_model=settings.deepeval_llm_model or settings.openai_model,
    )

    return [DeepEvalCriteriaEvaluator(client, settings.deepeval_criteria_threshold)]
