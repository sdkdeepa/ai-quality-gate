"""The only module allowed to import `deepeval` (or build the OpenAI-backed
judge model used purely for DeepEval's G-Eval metric).

Mirrors `app/evaluation/ragas/client.py` exactly, for the same reason that
module mirrors `app/providers/openai_provider.py`: every exception the
underlying SDK/deepeval can raise while scoring a metric is caught here and
mapped onto the **same** `ProviderErrorType` vocabulary already used for
provider failures and RAGAS evaluator failures — no third error-type enum.
`app/evaluation/deepeval/evaluator.py` never imports `deepeval`; it only
ever sees `DeepEvalScore` (success) or `DeepEvalEvaluatorError` (an
infrastructure failure) from this module. See DECISIONS.md #24.
"""

from dataclasses import dataclass

import openai

from app.providers.types import ProviderErrorType


@dataclass(frozen=True)
class DeepEvalScore:
    """A single normalized DeepEval metric result, with deepeval's own types stripped off."""

    value: float
    reason: str | None = None


class DeepEvalEvaluatorError(Exception):
    """Raised for any failure executing a DeepEval metric.

    Always an EVALUATOR INFRASTRUCTURE failure (the metric did not run) —
    never raised, and never to be treated as, a real (e.g. low) quality
    score. Callers (see `evaluator.py`) must catch this and represent it
    explicitly rather than defaulting to score=0, exactly like
    `RagasEvaluatorError` (Sprint 5).
    """

    def __init__(self, message: str, *, error_type: ProviderErrorType) -> None:
        super().__init__(message)
        self.error_type = error_type


class DeepEvalClient:
    """Owns the DeepEval-specific judge-model wiring and a small cache of
    constructed `GEval` metric instances (Sprint 6 ships one DeepEval
    evaluator — a configurable G-Eval custom-criteria check — but its
    criteria/threshold can vary per case via `case.metadata`, so metric
    instances are built lazily per distinct (name, criteria, params,
    threshold) combination and reused, rather than rebuilt every call).

    Like `RagasClient`, this reuses the *credentials/config*
    (`AQG_OPENAI_API_KEY`, a configurable judge model) but not the app's own
    `Provider` protocol — DeepEval's `GEval`/`LLMTestCase` shape has no
    equivalent of `Provider.generate()`, so translating through `Provider`
    would mean bending that contract to fit a framework it was never meant
    to describe.
    """

    def __init__(self, *, api_key: str, judge_model: str) -> None:
        from deepeval.models import OpenAIModel

        self._model = OpenAIModel(model=judge_model, api_key=api_key)
        self._metric_cache: dict[tuple, object] = {}

    def score_criteria(
        self,
        *,
        name: str,
        criteria: str,
        threshold: float,
        input_text: str,
        actual_output: str,
        expected_output: str | None = None,
        context: list[str] | None = None,
        retrieval_context: list[str] | None = None,
    ) -> DeepEvalScore:
        from deepeval.test_case import LLMTestCase, SingleTurnParams

        params = [SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT]
        test_case_kwargs = {"input": input_text, "actual_output": actual_output}
        if expected_output:
            params.append(SingleTurnParams.EXPECTED_OUTPUT)
            test_case_kwargs["expected_output"] = expected_output
        if context:
            params.append(SingleTurnParams.CONTEXT)
            test_case_kwargs["context"] = context
        if retrieval_context:
            params.append(SingleTurnParams.RETRIEVAL_CONTEXT)
            test_case_kwargs["retrieval_context"] = retrieval_context

        cache_key = (name, criteria, tuple(p.value for p in params), threshold)
        metric = self._metric_cache.get(cache_key)
        if metric is None:
            metric = self._build_metric(
                name=name, criteria=criteria, params=params, threshold=threshold
            )
            self._metric_cache[cache_key] = metric

        test_case = LLMTestCase(**test_case_kwargs)
        return self._run(lambda: self._measure(metric, test_case))

    def _build_metric(self, *, name: str, criteria: str, params: list, threshold: float):
        from deepeval.metrics import GEval

        return GEval(
            name=name,
            criteria=criteria,
            evaluation_params=params,
            model=self._model,
            threshold=threshold,
            # Sync mode: matches the Evaluator protocol's sync `evaluate()`
            # and avoids juggling an event loop inside a request thread —
            # same reasoning as RagasClient calling ragas metrics' `.score()`
            # rather than `.ascore()`.
            async_mode=False,
        )

    def _measure(self, metric, test_case):
        metric.measure(test_case, _show_indicator=False)
        return metric

    def _run(self, call) -> DeepEvalScore:
        from deepeval.errors import DeepEvalError

        try:
            metric = call()
        except openai.APITimeoutError as exc:
            raise DeepEvalEvaluatorError(str(exc), error_type=ProviderErrorType.TIMEOUT) from exc
        except openai.AuthenticationError as exc:
            raise DeepEvalEvaluatorError(
                str(exc), error_type=ProviderErrorType.AUTHENTICATION
            ) from exc
        except openai.RateLimitError as exc:
            raise DeepEvalEvaluatorError(str(exc), error_type=ProviderErrorType.RATE_LIMIT) from exc
        except openai.APIConnectionError as exc:
            raise DeepEvalEvaluatorError(
                str(exc), error_type=ProviderErrorType.UNAVAILABLE
            ) from exc
        except openai.APIStatusError as exc:
            raise DeepEvalEvaluatorError(
                str(exc), error_type=ProviderErrorType.UNAVAILABLE
            ) from exc
        except openai.OpenAIError as exc:
            raise DeepEvalEvaluatorError(
                str(exc), error_type=ProviderErrorType.UNAVAILABLE
            ) from exc
        except DeepEvalError as exc:
            # deepeval's own validation/dependency errors (e.g. a malformed
            # judge response it couldn't parse into a score) - framework
            # failure, not a quality signal.
            raise DeepEvalEvaluatorError(
                str(exc), error_type=ProviderErrorType.UNAVAILABLE
            ) from exc
        except DeepEvalEvaluatorError:
            raise
        except Exception as exc:  # noqa: BLE001 - any other dependency failure
            raise DeepEvalEvaluatorError(
                str(exc), error_type=ProviderErrorType.UNAVAILABLE
            ) from exc

        try:
            value = float(metric.score)
        except (TypeError, ValueError) as exc:
            raise DeepEvalEvaluatorError(
                f"DeepEval metric returned a non-numeric score: {metric.score!r}",
                error_type=ProviderErrorType.MALFORMED_RESPONSE,
            ) from exc

        return DeepEvalScore(value=value, reason=getattr(metric, "reason", None))
