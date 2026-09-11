from datetime import UTC, datetime

from app.core.exceptions import MissingFixtureError
from app.domain.case_result import CaseResult
from app.domain.enums import RunStatus
from app.domain.evaluation_case import EvaluationCase
from app.domain.evaluation_run import EvaluationRun
from app.domain.golden_dataset import GoldenDataset
from app.evaluation.base import Evaluator
from app.evaluation.deterministic import DEFAULT_EVALUATORS
from app.evaluation.types import EvaluationInput, FixtureResponse
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

    def __init__(self, evaluators: list[Evaluator] | None = None) -> None:
        self._evaluators = evaluators if evaluators is not None else list(DEFAULT_EVALUATORS)

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
        run = EvaluationRun(
            dataset_version=dataset.version,
            provider=provider.name,
            model=provider.model,
            status=RunStatus.RUNNING,
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
        request = ProviderRequest(
            case_id=case.id,
            prompt=case.query,
            json_schema=case.metadata.get("json_schema"),
        )
        response = provider.generate(request)
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
                evaluator.evaluate(evaluation_input)
                for evaluator in evaluators
                if evaluator.applies_to(case)
            ]
            passed = all(m.passed for m in metric_results) if metric_results else True

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
                {"error_type": response.error.error_type.value, "message": response.error.message}
                if response.error is not None
                else None
            ),
        )
