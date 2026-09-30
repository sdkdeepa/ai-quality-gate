import logging
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import UTC, datetime

from openinference.semconv.trace import OpenInferenceSpanKindValues, SpanAttributes
from opentelemetry import trace
from opentelemetry.trace import Tracer

from app.core.exceptions import MissingFixtureError
from app.domain.case_result import CaseResult
from app.domain.enums import RunStatus
from app.domain.evaluation_case import EvaluationCase
from app.domain.evaluation_run import EvaluationRun
from app.domain.golden_dataset import GoldenDataset
from app.domain.metric_result import MetricResult
from app.evaluation.base import Evaluator
from app.evaluation.deterministic import DEFAULT_EVALUATORS
from app.evaluation.types import EvaluationInput, FixtureResponse
from app.observability.tracing import trace_id_hex
from app.providers.base import Provider
from app.providers.deterministic import DeterministicProvider
from app.providers.types import ProviderErrorType, ProviderRequest
from app.reliability.retry import retry_provider_call

logger = logging.getLogger("app.evaluation")


class EvaluationRunner:
    """Runs a GoldenDataset's cases through deterministic evaluators.

    Cases are sourced from a Provider (dataset -> provider -> response ->
    evaluators) — DeterministicProvider for the fixture-driven path tests and
    CI rely on, or a live provider (OpenAIProvider, GeminiProvider, ...) for a
    real system-under-test call. Evaluators never see a raw provider or its
    SDK: they only ever get an EvaluationInput built from a ProviderResponse.
    """

    def __init__(
        self,
        evaluators: list[Evaluator] | None = None,
        *,
        tracer: Tracer | None = None,
        provider_retry_max_attempts: int = 1,
        provider_retry_base_delay_seconds: float = 0.5,
        evaluator_timeout_seconds: float | None = None,
    ) -> None:
        self._evaluators = evaluators if evaluators is not None else list(DEFAULT_EVALUATORS)
        # Sprint 9: defaults to OpenTelemetry's own no-op tracer, so every
        # existing caller (all of Sprint 1-8's tests included) that builds
        # an EvaluationRunner without a `tracer` keeps working exactly as
        # before — see `app/observability/tracing.py`.
        self._tracer = tracer or trace.get_tracer(__name__)
        # Sprint 12: both default to "off" (1 attempt = no retries, no
        # per-evaluator timeout) so every existing caller/test that builds
        # an EvaluationRunner without these keyword arguments keeps
        # working exactly as before.
        self._provider_retry_max_attempts = provider_retry_max_attempts
        self._provider_retry_base_delay_seconds = provider_retry_base_delay_seconds
        self._evaluator_timeout_seconds = evaluator_timeout_seconds

    def run(
        self,
        dataset: GoldenDataset,
        fixtures: dict[str, FixtureResponse],
        *,
        provider: str = "deterministic",
        model: str = "fixture-v1",
        frameworks: set[str] | None = None,
    ) -> tuple[EvaluationRun, list[CaseResult]]:
        """Fixture-driven convenience path: wraps `fixtures` as a DeterministicProvider.

        Raises MissingFixtureError upfront if any case lacks a fixture, matching
        Sprint 2 behavior exactly (a live provider has no equivalent upfront
        check — it fails per-case instead, via a normalized ProviderError).

        `frameworks` (Sprint 6): restrict which evaluators run, by their
        `Evaluator.framework` ("deterministic"/"ragas"/"deepeval"/...). `None`
        (the default) runs every evaluator the runner was constructed with —
        unchanged from Sprint 1-5 behavior.
        """
        missing = [case.id for case in dataset.cases if case.id not in fixtures]
        if missing:
            raise MissingFixtureError(f"no fixture response for case ids: {missing}")

        deterministic_provider = DeterministicProvider(fixtures, model=model, name=provider)
        return self.run_with_provider(dataset, deterministic_provider, frameworks=frameworks)

    def run_with_provider(
        self, dataset: GoldenDataset, provider: Provider, *, frameworks: set[str] | None = None
    ) -> tuple[EvaluationRun, list[CaseResult]]:
        with self._tracer.start_as_current_span(
            "evaluation_run",
            attributes={
                SpanAttributes.OPENINFERENCE_SPAN_KIND: OpenInferenceSpanKindValues.CHAIN.value,
                "dataset.name": dataset.name,
                "dataset.version": dataset.version,
                "provider.name": provider.name,
                "llm.model_name": provider.model,
                "case.count": len(dataset.cases),
            },
        ) as run_span:
            run = EvaluationRun(
                dataset_name=dataset.name,
                dataset_version=dataset.version,
                provider=provider.name,
                model=provider.model,
                status=RunStatus.RUNNING,
                trace_id=trace_id_hex(run_span),
            )

            case_results = [
                self._evaluate_case_isolated(case, provider, frameworks=frameworks)
                for case in dataset.cases
            ]

            run.status = (
                RunStatus.PARTIAL if any(c.partial for c in case_results) else RunStatus.COMPLETED
            )
            run.completed_at = datetime.now(UTC)
            logger.info(
                "evaluation run completed",
                extra={
                    "run_id": run.id,
                    "trace_id": run.trace_id,
                    "dataset_name": run.dataset_name,
                    "dataset_version": run.dataset_version,
                    "provider": run.provider,
                    "model": run.model,
                    "run_status": run.status.value,
                    "case_count": len(case_results),
                    "passed_count": sum(1 for c in case_results if c.passed),
                    "partial_count": sum(1 for c in case_results if c.partial),
                },
            )

            return run, case_results

    def _evaluate_case_isolated(
        self, case: EvaluationCase, provider: Provider, *, frameworks: set[str] | None
    ) -> CaseResult:
        """Sprint 12: the outermost failure-isolation boundary — one
        case's totally unexpected crash (anything not already caught and
        normalized by `evaluate_case`'s own provider/evaluator handling)
        must never lose every other case's already-computed results. This
        is deliberately a second, independent safety net on top of
        `_evaluate_with_span`'s per-evaluator isolation, not a replacement
        for it: that one keeps one bad evaluator from ruining one case;
        this one keeps one bad case from ruining the whole run.
        """
        try:
            return self.evaluate_case(case, provider, frameworks=frameworks)
        except Exception as exc:  # noqa: BLE001 - isolate one case's bug from the whole run
            logger.error(
                "case %s raised an unexpected exception during evaluation - isolated, "
                "other cases in this run still ran",
                case.id,
                exc_info=True,
                extra={"case_id": case.id},
            )
            return CaseResult(
                case_id=case.id,
                response="",
                latency_ms=0.0,
                input_tokens=0,
                output_tokens=0,
                estimated_cost=0.0,
                passed=False,
                critical_failure=case.critical,
                partial=True,
                error={"error_type": ProviderErrorType.UNAVAILABLE.value, "message": str(exc)},
            )

    def evaluate_case(
        self, case: EvaluationCase, provider: Provider, *, frameworks: set[str] | None = None
    ) -> CaseResult:
        """Run one case through `provider` and grade it. Public so callers that
        want a single case's result without a full dataset run (e.g. the RAG
        "evaluate a case" endpoint) can reuse this instead of re-implementing
        the provider-response-to-CaseResult logic.

        `frameworks`: see `run()`. Filtering happens here (not just in `run`)
        so a caller going straight to `evaluate_case` — e.g. `RAGService` —
        gets the same selection behavior.
        """
        with self._tracer.start_as_current_span(
            "case",
            attributes={
                SpanAttributes.OPENINFERENCE_SPAN_KIND: OpenInferenceSpanKindValues.CHAIN.value,
                SpanAttributes.INPUT_VALUE: case.query,
                "case.id": case.id,
                "case.category": case.category,
                "case.critical": case.critical,
            },
        ) as case_span:
            request = ProviderRequest(
                case_id=case.id,
                prompt=case.query,
                json_schema=case.metadata.get("json_schema"),
            )
            response = self._generate_with_span(provider, request)
            evaluators = (
                self._evaluators
                if frameworks is None
                else [e for e in self._evaluators if e.framework in frameworks]
            )

            if response.error is not None:
                metric_results = []
                passed = False
            else:
                evaluation_input = EvaluationInput(
                    case=case,
                    response=response.text,
                    retrieved_context=response.retrieved_context,
                    latency_ms=response.latency_ms,
                    input_tokens=response.input_tokens or 0,
                    output_tokens=response.output_tokens or 0,
                    estimated_cost=response.estimated_cost or 0.0,
                )
                metric_results = [
                    self._evaluate_with_span(evaluator, evaluation_input)
                    for evaluator in evaluators
                    if evaluator.applies_to(case)
                ]
                passed = all(m.passed for m in metric_results) if metric_results else True

            case_span.set_attribute(SpanAttributes.OUTPUT_VALUE, response.text)
            case_span.set_attribute("case.passed", passed)
            partial = any("error_type" in m.metadata for m in metric_results)
            case_span.set_attribute("case.partial", partial)

            return CaseResult(
                case_id=case.id,
                response=response.text,
                retrieved_context=response.retrieved_context,
                latency_ms=response.latency_ms,
                input_tokens=response.input_tokens or 0,
                output_tokens=response.output_tokens or 0,
                estimated_cost=response.estimated_cost or 0.0,
                metric_results=metric_results,
                passed=passed,
                critical_failure=case.critical and not passed,
                partial=partial,
                error=(
                    {
                        "error_type": response.error.error_type.value,
                        "message": response.error.message,
                    }
                    if response.error is not None
                    else None
                ),
            )

    def _generate_with_span(self, provider: Provider, request: ProviderRequest):
        """Wraps one `Provider.generate()` call (requirement: "provider
        calls", "generation spans", "latency", "provider/model metadata",
        "token usage"). For a RAG case, `provider` is a `RAGProvider`, so
        `Retriever.retrieve()`'s own "retrieval" span (Sprint 9,
        `app/rag/retriever.py`) is created *inside* this span's context —
        giving retrieval and generation distinct, separately-visible spans
        (requirement: "retrieval and generation visible separately")
        without this method needing to know RAG exists at all.

        Sprint 12: retried (bounded, exponential backoff) via
        `retry_provider_call` when `AQG_PROVIDER_RETRY_MAX_ATTEMPTS > 1`
        and the failure is one `ProviderError.retryable` calls transient
        (TIMEOUT/RATE_LIMIT/UNAVAILABLE) — a bad key or a malformed
        response is returned on the first attempt with no retry, since
        retrying either wastes time on a failure retrying cannot fix.
        """
        with self._tracer.start_as_current_span(
            "provider_call",
            attributes={
                SpanAttributes.OPENINFERENCE_SPAN_KIND: OpenInferenceSpanKindValues.LLM.value,
                SpanAttributes.LLM_PROVIDER: provider.name,
                SpanAttributes.LLM_MODEL_NAME: provider.model,
                SpanAttributes.INPUT_VALUE: request.prompt,
            },
        ) as span:
            response = retry_provider_call(
                lambda: provider.generate(request),
                max_attempts=self._provider_retry_max_attempts,
                base_delay_seconds=self._provider_retry_base_delay_seconds,
            )
            span.set_attribute(SpanAttributes.OUTPUT_VALUE, response.text)
            span.set_attribute("llm.latency_ms", response.latency_ms)
            if response.input_tokens is not None:
                span.set_attribute(SpanAttributes.LLM_TOKEN_COUNT_PROMPT, response.input_tokens)
            if response.output_tokens is not None:
                span.set_attribute(
                    SpanAttributes.LLM_TOKEN_COUNT_COMPLETION, response.output_tokens
                )
            if response.estimated_cost is not None:
                span.set_attribute(SpanAttributes.LLM_COST_TOTAL, response.estimated_cost)
            if response.error is not None:
                span.set_attribute("error.type", response.error.error_type.value)
                span.set_attribute("error.message", response.error.message)
            return response

    def _evaluate_with_span(self, evaluator: Evaluator, evaluation_input: EvaluationInput):
        """Wraps one `Evaluator.evaluate()` call (requirement: "evaluator
        execution"). Every framework — deterministic, RAGAS, DeepEval, the
        OpenAI-Evals-concept adapters — is instrumented identically here,
        at the one place they're all invoked; none of them (nor
        `app/policy/`) has any idea this span exists.

        Sprint 12 requirement: "evaluator timeouts", "failure isolation
        between frameworks", "graceful degradation", "explicit partial-
        evaluation semantics". If this evaluator times out
        (`AQG_EVALUATOR_TIMEOUT_SECONDS`) or raises ANY unexpected
        exception (a bug in that one evaluator/framework — not the
        normalized infrastructure failures RAGAS/DeepEval/OpenAI-Evals
        clients already handle internally, which still return a normal
        MetricResult), this is caught here and converted into an explicit
        MetricResult carrying `metadata["error_type"]` — the exact same
        convention Sprint 5/6/7's framework adapters use for their own
        infrastructure failures — rather than letting it propagate and
        take down the entire case (and, before this sprint, the entire
        run: `evaluate_case`'s list comprehension had no per-evaluator
        isolation at all). `app/policy/engine.py`'s existing
        `_metric_status()` classifies this as `infrastructure_error`
        automatically, with no changes needed there.
        """
        with self._tracer.start_as_current_span(
            evaluator.name,
            attributes={
                SpanAttributes.OPENINFERENCE_SPAN_KIND: OpenInferenceSpanKindValues.EVALUATOR.value,
                "evaluator.name": evaluator.name,
                "evaluator.framework": evaluator.framework,
            },
        ) as span:
            try:
                result = self._call_evaluator(evaluator, evaluation_input)
            except FutureTimeoutError:
                logger.error(
                    "evaluator %s timed out after %ss - isolated, other evaluators for "
                    "this case still ran",
                    evaluator.name,
                    self._evaluator_timeout_seconds,
                    extra={
                        "evaluator_name": evaluator.name,
                        "evaluator_framework": evaluator.framework,
                        "timeout_seconds": self._evaluator_timeout_seconds,
                    },
                )
                span.set_attribute("evaluator.status", "timeout")
                result = _isolated_failure_result(
                    evaluator,
                    ProviderErrorType.TIMEOUT,
                    f"evaluator did not return within {self._evaluator_timeout_seconds}s",
                )
            except Exception as exc:  # noqa: BLE001 - isolate one evaluator's bug from the case/run
                logger.error(
                    "evaluator %s raised an unexpected exception - isolated, other "
                    "evaluators for this case still ran",
                    evaluator.name,
                    exc_info=True,
                    extra={
                        "evaluator_name": evaluator.name,
                        "evaluator_framework": evaluator.framework,
                    },
                )
                span.set_attribute("evaluator.status", "crashed")
                result = _isolated_failure_result(
                    evaluator, ProviderErrorType.UNAVAILABLE, str(exc)
                )

            span.set_attribute("evaluator.metric_name", result.metric_name)
            span.set_attribute(SpanAttributes.EVALUATIONS, str(result.score))
            span.set_attribute("evaluator.score", result.score)
            span.set_attribute("evaluator.passed", result.passed)
            return result

    def _call_evaluator(self, evaluator: Evaluator, evaluation_input: EvaluationInput):
        if self._evaluator_timeout_seconds is None:
            return evaluator.evaluate(evaluation_input)

        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(evaluator.evaluate, evaluation_input)
        try:
            return future.result(timeout=self._evaluator_timeout_seconds)
        finally:
            # wait=False: a genuine timeout must never itself hang waiting
            # for the (possibly still-running-forever) worker thread to
            # finish. Python has no cross-platform way to forcibly kill a
            # thread, so a timed-out call's thread is abandoned, not
            # killed — it will run to completion in the background with
            # its result discarded. See DECISIONS.md's Sprint 12 entry.
            pool.shutdown(wait=False, cancel_futures=True)


def _isolated_failure_result(
    evaluator: Evaluator, error_type: ProviderErrorType, detail: str
) -> MetricResult:
    """Builds the explicit, non-vacuous MetricResult a timed-out or
    crashed evaluator is replaced with (Sprint 12). Uses the exact same
    `metadata["error_type"]` convention Sprint 5/6/7's own framework
    adapters use for THEIR infrastructure failures — so
    `app/policy/engine.py`'s existing `_metric_status()` classifies this
    as `infrastructure_error` (never a quality score of 0) with no
    changes needed there, and a required-metric policy's
    `on_infrastructure_failure` action (block/warn/ignore) applies to a
    runner-level isolation failure exactly the same way it already
    applies to a RAGAS/DeepEval/OpenAI-Evals judge's own infra failure.
    """
    return MetricResult(
        metric_name=evaluator.name,
        score=0.0,
        threshold=1.0,
        passed=False,
        framework=evaluator.framework,
        explanation=(
            f"evaluator infrastructure failure ({error_type.value}): {detail}. "
            "This is not a quality score - the evaluator did not execute "
            "(isolated so other evaluators for this case still ran)."
        ),
        metadata={"error_type": error_type.value},
    )
