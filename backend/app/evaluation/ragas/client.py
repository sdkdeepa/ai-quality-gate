"""The only module allowed to import `ragas` (or build the OpenAI client used
purely as RAGAS's LLM judge / embeddings backend).

Mirrors `app/providers/openai_provider.py`'s role for the Provider contract:
every exception the underlying SDKs can raise while scoring a metric is
caught here and mapped onto the same `ProviderErrorType` vocabulary the rest
of the app already uses for provider failures. That reuse is deliberate —
"RAGAS dependency failure", "evaluator model timeout", "authentication
failure", "rate limit", "malformed evaluator response", and "unavailable
evaluator service" (Sprint 5 spec) are exactly TIMEOUT / AUTHENTICATION /
RATE_LIMIT / MALFORMED_RESPONSE / UNAVAILABLE already defined on
`ProviderErrorType` — no need for a second error-type enum.

`app/evaluation/ragas/evaluator.py` never imports `ragas` or `openai`
itself; it only ever sees `RagasScore` (success) or `RagasEvaluatorError`
(infrastructure failure) from this module. See DECISIONS.md #22.
"""

from dataclasses import dataclass

import openai

from app.providers.types import ProviderErrorType


@dataclass(frozen=True)
class RagasScore:
    """A single normalized RAGAS metric result, with ragas's own types stripped off."""

    value: float
    reason: str | None = None


class RagasEvaluatorError(Exception):
    """Raised for any failure executing a RAGAS metric.

    This is always an EVALUATOR INFRASTRUCTURE failure (the metric did not
    run) — never raised, and never to be treated as, a real (e.g. low)
    quality score. Callers (see `evaluator.py`) must catch this and
    represent it explicitly rather than defaulting to score=0.
    """

    def __init__(self, message: str, *, error_type: ProviderErrorType) -> None:
        super().__init__(message)
        self.error_type = error_type


class RagasClient:
    """Owns the RAGAS-specific LLM/embeddings wiring and the four metric
    instances, built once and reused across evaluations.

    RAGAS's `llm_factory`/`embedding_factory` need their own wrapped client
    object, not our `Provider` protocol — Provider.generate() has no
    equivalent of RAGAS's structured-output judge calls, so translating
    through Provider would mean bending that contract to fit a framework it
    was never meant to describe. This class is the isolated translation
    layer the sprint plan calls for: it reuses the *credentials/config*
    (AQG_OPENAI_API_KEY, AQG_OPENAI_MODEL, AQG_PROVIDER_TIMEOUT_SECONDS) but
    not the Provider interface itself.
    """

    def __init__(
        self,
        *,
        api_key: str,
        judge_model: str,
        embedding_model: str,
        timeout_seconds: float,
    ) -> None:
        from ragas.embeddings.base import embedding_factory
        from ragas.llms import llm_factory
        from ragas.metrics.collections import (
            AnswerRelevancy,
            ContextPrecision,
            ContextRecall,
            Faithfulness,
        )

        client = openai.OpenAI(api_key=api_key, timeout=timeout_seconds)
        llm = llm_factory(judge_model, client=client)
        embeddings = embedding_factory("openai", embedding_model, client=client)

        self._faithfulness = Faithfulness(llm=llm)
        self._answer_relevancy = AnswerRelevancy(llm=llm, embeddings=embeddings)
        self._context_precision = ContextPrecision(llm=llm)
        self._context_recall = ContextRecall(llm=llm)

    def score_faithfulness(
        self, *, user_input: str, response: str, retrieved_contexts: list[str]
    ) -> RagasScore:
        return self._run(
            lambda: self._faithfulness.score(
                user_input=user_input,
                response=response,
                retrieved_contexts=retrieved_contexts,
            )
        )

    def score_answer_relevancy(self, *, user_input: str, response: str) -> RagasScore:
        return self._run(
            lambda: self._answer_relevancy.score(user_input=user_input, response=response)
        )

    def score_context_precision(
        self, *, user_input: str, reference: str, retrieved_contexts: list[str]
    ) -> RagasScore:
        return self._run(
            lambda: self._context_precision.score(
                user_input=user_input,
                reference=reference,
                retrieved_contexts=retrieved_contexts,
            )
        )

    def score_context_recall(
        self, *, user_input: str, reference: str, retrieved_contexts: list[str]
    ) -> RagasScore:
        return self._run(
            lambda: self._context_recall.score(
                user_input=user_input,
                retrieved_contexts=retrieved_contexts,
                reference=reference,
            )
        )

    def _run(self, call) -> RagasScore:
        try:
            result = call()
        except openai.APITimeoutError as exc:
            raise RagasEvaluatorError(str(exc), error_type=ProviderErrorType.TIMEOUT) from exc
        except openai.AuthenticationError as exc:
            raise RagasEvaluatorError(
                str(exc), error_type=ProviderErrorType.AUTHENTICATION
            ) from exc
        except openai.RateLimitError as exc:
            raise RagasEvaluatorError(str(exc), error_type=ProviderErrorType.RATE_LIMIT) from exc
        except openai.APIConnectionError as exc:
            raise RagasEvaluatorError(str(exc), error_type=ProviderErrorType.UNAVAILABLE) from exc
        except openai.APIStatusError as exc:
            raise RagasEvaluatorError(str(exc), error_type=ProviderErrorType.UNAVAILABLE) from exc
        except openai.OpenAIError as exc:
            raise RagasEvaluatorError(str(exc), error_type=ProviderErrorType.UNAVAILABLE) from exc
        except RagasEvaluatorError:
            raise
        except Exception as exc:  # noqa: BLE001 - any other RAGAS/instructor/dependency failure
            # Covers "RAGAS dependency failure" / "unavailable evaluator
            # service" from the sprint spec: anything from ragas's own
            # exception hierarchy, instructor's structured-output retries
            # being exhausted, etc. Always normalized — never left to
            # propagate as a bare exception out of evaluate().
            raise RagasEvaluatorError(str(exc), error_type=ProviderErrorType.UNAVAILABLE) from exc

        try:
            value = float(result.value)
        except (TypeError, ValueError) as exc:
            raise RagasEvaluatorError(
                f"RAGAS metric returned a non-numeric value: {result.value!r}",
                error_type=ProviderErrorType.MALFORMED_RESPONSE,
            ) from exc

        return RagasScore(value=value, reason=getattr(result, "reason", None))
