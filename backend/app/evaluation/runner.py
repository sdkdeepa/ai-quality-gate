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
from app.evaluation.base import Evaluator
from app.evaluation.deterministic import DEFAULT_EVALUATORS
from app.evaluation.types import EvaluationInput, FixtureResponse
from app.observability.tracing import trace_id_hex
from app.providers.base import Provider
from app.providers.deterministic import DeterministicProvider
from app.providers.types import ProviderRequest


class EvaluationRunner:
    """Runs a GoldenDataset's cases through deterministic evaluators.

    Cases are sourced from a Provider (dataset -> provider -> response ->
    evaluators) — DeterministicProvider for the fixture-driven path tests and
    CI rely on, or a live provider (OpenAIProvider, GeminiProvider, ...) for a
    real system-under-test call. Evaluators never see a raw provider or its
    SDK: they only ever get an EvaluationInput built from a ProviderResponse.
    """

    def __init__(
        self, evaluators: list[Evaluator] | None = None, *, tracer: Tracer | None = None
    ) -> None:
        self._evaluators = evaluators if evaluators is not None else list(DEFAULT_EVALUATORS)
        # Sprint 9: defaults to OpenTelemetry's own no-op tracer, so every
        # existing caller (all of Sprint 1-8's tests included) that builds
        # an EvaluationRunner without a `tracer` keeps working exactly as
        # before — see `app/observability/tracing.py`.
        self._tracer = tracer or trace.get_tracer(__name__)

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
                self.evaluate_case(case, provider, frameworks=frameworks) for case in dataset.cases
            ]

            run.status = RunStatus.COMPLETED
            run.completed_at = datetime.now(UTC)

            return run, case_results

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
            response = provider.generate(request)
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
        `app/policy/`) has any idea this span exists."""
        with self._tracer.start_as_current_span(
            evaluator.name,
            attributes={
                SpanAttributes.OPENINFERENCE_SPAN_KIND: OpenInferenceSpanKindValues.EVALUATOR.value,
                "evaluator.name": evaluator.name,
                "evaluator.framework": evaluator.framework,
            },
        ) as span:
            result = evaluator.evaluate(evaluation_input)
            span.set_attribute("evaluator.metric_name", result.metric_name)
            span.set_attribute(SpanAttributes.EVALUATIONS, str(result.score))
            span.set_attribute("evaluator.score", result.score)
            span.set_attribute("evaluator.passed", result.passed)
            return result
