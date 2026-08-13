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


class EvaluationRunner:
    """Runs a GoldenDataset's cases through deterministic evaluators using fixture responses.

    No live model provider exists yet (Sprint 2 scope): the runner is fed
    pre-recorded FixtureResponses so evaluation logic can be exercised and
    tested end to end without calling out to a real system under test.
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
    ) -> tuple[EvaluationRun, list[CaseResult]]:
        missing = [case.id for case in dataset.cases if case.id not in fixtures]
        if missing:
            raise MissingFixtureError(f"no fixture response for case ids: {missing}")

        run = EvaluationRun(
            dataset_version=dataset.version,
            provider=provider,
            model=model,
            status=RunStatus.RUNNING,
        )

        case_results = [self._evaluate_case(case, fixtures[case.id]) for case in dataset.cases]

        run.status = RunStatus.COMPLETED
        run.completed_at = datetime.now(UTC)

        return run, case_results

    def _evaluate_case(self, case: EvaluationCase, fixture: FixtureResponse) -> CaseResult:
        evaluation_input = EvaluationInput(
            case=case,
            response=fixture.response,
            retrieved_context=fixture.retrieved_context,
            latency_ms=fixture.latency_ms,
            input_tokens=fixture.input_tokens,
            output_tokens=fixture.output_tokens,
            estimated_cost=fixture.estimated_cost,
        )
        metric_results = [
            evaluator.evaluate(evaluation_input)
            for evaluator in self._evaluators
            if evaluator.applies_to(case)
        ]
        passed = all(m.passed for m in metric_results) if metric_results else True
        return CaseResult(
            case_id=case.id,
            response=fixture.response,
            retrieved_context=fixture.retrieved_context,
            latency_ms=fixture.latency_ms,
            input_tokens=fixture.input_tokens,
            output_tokens=fixture.output_tokens,
            estimated_cost=fixture.estimated_cost,
            metric_results=metric_results,
            passed=passed,
            critical_failure=case.critical and not passed,
        )
