"""Turns Settings into a list of RAGAS Evaluators.

`main.py` calls `build_ragas_evaluators(settings)` once at app startup and
extends `EvaluationRunner`'s evaluator list with the result — see
DECISIONS.md #21. This is a plain startup-time configuration check, not a
per-request `AppError`: an app that starts with `AQG_RAGAS_ENABLED=true` and
no API key should fail fast and loudly, the same way a missing required env
var would in any other service, rather than silently falling back to
"RAGAS disabled".
"""

from app.core.config import Settings
from app.evaluation.base import Evaluator
from app.evaluation.ragas.client import RagasClient
from app.evaluation.ragas.evaluator import (
    RagasAnswerRelevancyEvaluator,
    RagasContextPrecisionEvaluator,
    RagasContextRecallEvaluator,
    RagasFaithfulnessEvaluator,
)

KNOWN_RAGAS_METRICS = (
    "faithfulness",
    "answer_relevancy",
    "context_precision",
    "context_recall",
)


class RagasConfigurationError(RuntimeError):
    """Raised at app-startup time when AQG_RAGAS_ENABLED=true but required
    configuration is missing or invalid. Deliberately a plain RuntimeError,
    not an `AppError` — there is no HTTP request to attach a JSON error body
    to yet at this point in `create_app()`."""


def build_ragas_evaluators(settings: Settings) -> list[Evaluator]:
    """Returns [] when RAGAS is disabled (the default) — no `ragas`/`openai`
    judge-client objects are constructed at all in that case, so
    AQG_RAGAS_ENABLED=false (default) has zero behavioral or import-time
    impact on the rest of the Gate."""
    if not settings.ragas_enabled:
        return []

    if not settings.openai_api_key:
        raise RagasConfigurationError(
            "AQG_RAGAS_ENABLED=true requires AQG_OPENAI_API_KEY — RAGAS's LLM "
            "judge/embeddings currently reuse the OpenAI provider's key. "
            "Gemini-backed RAGAS judging is not implemented this sprint "
            "(see PROJECT_STATE.md 'Outstanding work')."
        )

    selected = settings.ragas_metrics_list
    unknown = [metric for metric in selected if metric not in KNOWN_RAGAS_METRICS]
    if unknown:
        raise RagasConfigurationError(
            f"unknown AQG_RAGAS_METRICS entries {unknown}; "
            f"expected a comma-separated subset of {KNOWN_RAGAS_METRICS}"
        )

    client = RagasClient(
        api_key=settings.openai_api_key,
        judge_model=settings.ragas_llm_model or settings.openai_model,
        embedding_model=settings.ragas_embedding_model,
        timeout_seconds=settings.provider_timeout_seconds,
    )

    evaluators: list[Evaluator] = []
    if "faithfulness" in selected:
        evaluators.append(RagasFaithfulnessEvaluator(client, settings.ragas_faithfulness_threshold))
    if "answer_relevancy" in selected:
        evaluators.append(
            RagasAnswerRelevancyEvaluator(client, settings.ragas_answer_relevancy_threshold)
        )
    if "context_precision" in selected:
        evaluators.append(
            RagasContextPrecisionEvaluator(client, settings.ragas_context_precision_threshold)
        )
    if "context_recall" in selected:
        evaluators.append(
            RagasContextRecallEvaluator(client, settings.ragas_context_recall_threshold)
        )
    return evaluators
