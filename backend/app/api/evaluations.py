from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api._view import metrics_by_framework
from app.api.deps import get_evaluation_service
from app.domain.case_result import CaseResult
from app.domain.evaluation_run import EvaluationRun
from app.services.evaluation_service import EvaluationService

router = APIRouter(prefix="/evaluations", tags=["evaluations"])


class RunEvaluationRequest(BaseModel):
    dataset_name: str
    dataset_version: str | None = None
    provider: Literal["deterministic", "openai", "gemini"] = "deterministic"
    # Sprint 6 requirement #4: API-based evaluator-combination selection.
    # None (default) runs every evaluator the app was started with (Sprint
    # 1-5 behavior, unchanged); a subset like ["deterministic", "ragas"]
    # restricts which frameworks contribute MetricResults for this run,
    # regardless of what's enabled at the process level. Requesting a
    # framework that isn't enabled (e.g. "deepeval" when
    # AQG_DEEPEVAL_ENABLED=false) just yields zero evaluators from that
    # framework, not an error - the runner was never given any to filter.
    frameworks: list[Literal["deterministic", "ragas", "deepeval"]] | None = None


def _run_summary(
    run: EvaluationRun, results: list[CaseResult], *, include_cases: bool = False
) -> dict:
    passed_count = sum(1 for result in results if result.passed)
    critical_failure_case_ids = [result.case_id for result in results if result.critical_failure]
    body = {
        "run": run,
        "case_count": len(results),
        "passed_count": passed_count,
        "failed_count": len(results) - passed_count,
        "critical_failure_case_ids": critical_failure_case_ids,
    }
    if include_cases:
        body["case_results"] = results
        # Sprint 5 requirement #8: let a caller inspect deterministic vs.
        # RAGAS metrics for the same case side by side, keyed by case_id ->
        # framework -> that framework's MetricResults. Additive only — the
        # existing `case_results` shape (and every Sprint 1-4 consumer of
        # it) is unchanged.
        body["metrics_by_framework"] = {
            result.case_id: metrics_by_framework(result) for result in results
        }
    return body


@router.post("/runs")
def run_evaluation(
    request: RunEvaluationRequest,
    evaluation_service: Annotated[EvaluationService, Depends(get_evaluation_service)],
) -> dict:
    """Run every case in a dataset through the configured evaluators.

    `provider` selects the response source: "deterministic" (default) replays
    fixture responses for reproducible tests/CI; "openai"/"gemini" call the
    live API (requires the matching AQG_OPENAI_API_KEY/AQG_GEMINI_API_KEY).

    `frameworks` (Sprint 6) optionally restricts which evaluator frameworks
    grade this run — e.g. `["deterministic", "ragas"]` to exclude DeepEval
    for one run without disabling it process-wide. Omit for "every enabled
    framework" (unchanged Sprint 1-5 behavior).
    """
    frameworks = set(request.frameworks) if request.frameworks is not None else None
    run = evaluation_service.run(
        request.dataset_name, request.dataset_version, request.provider, frameworks=frameworks
    )
    _, results = evaluation_service.get_run(run.id)
    return _run_summary(run, results)


@router.get("/runs/{run_id}")
def get_evaluation_run(
    run_id: str,
    evaluation_service: Annotated[EvaluationService, Depends(get_evaluation_service)],
) -> dict:
    """Inspect a past evaluation run, including every case's metric results."""
    run, results = evaluation_service.get_run(run_id)
    return _run_summary(run, results, include_cases=True)
