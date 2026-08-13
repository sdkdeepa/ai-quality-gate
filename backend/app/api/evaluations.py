from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import get_evaluation_service
from app.domain.case_result import CaseResult
from app.domain.evaluation_run import EvaluationRun
from app.services.evaluation_service import EvaluationService

router = APIRouter(prefix="/evaluations", tags=["evaluations"])


class RunDeterministicEvaluationRequest(BaseModel):
    dataset_name: str
    dataset_version: str | None = None


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
    return body


@router.post("/runs")
def run_deterministic_evaluation(
    request: RunDeterministicEvaluationRequest,
    evaluation_service: Annotated[EvaluationService, Depends(get_evaluation_service)],
) -> dict:
    """Run every case in a dataset through the deterministic evaluators using fixture responses."""
    run = evaluation_service.run_deterministic(request.dataset_name, request.dataset_version)
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
