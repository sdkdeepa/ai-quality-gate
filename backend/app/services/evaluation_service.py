from app.core.exceptions import NotFoundError
from app.domain.case_result import CaseResult
from app.domain.evaluation_run import EvaluationRun
from app.evaluation.runner import EvaluationRunner
from app.repositories.in_memory import InMemoryCaseResultStore, InMemoryRepository
from app.services.dataset_service import DatasetService


class EvaluationService:
    """Orchestrates a deterministic evaluation run: resolve dataset + fixtures, run, persist."""

    def __init__(
        self,
        dataset_service: DatasetService,
        runner: EvaluationRunner,
        run_repository: InMemoryRepository[EvaluationRun],
        case_result_store: InMemoryCaseResultStore,
    ) -> None:
        self._dataset_service = dataset_service
        self._runner = runner
        self._run_repository = run_repository
        self._case_result_store = case_result_store

    def run_deterministic(
        self, dataset_name: str, dataset_version: str | None = None
    ) -> EvaluationRun:
        dataset = self._dataset_service.get_dataset(dataset_name, dataset_version)
        fixtures = self._dataset_service.get_fixtures(dataset)
        run, case_results = self._runner.run(dataset, fixtures)
        self._run_repository.add(run)
        self._case_result_store.save(run.id, case_results)
        return run

    def get_run(self, run_id: str) -> tuple[EvaluationRun, list[CaseResult]]:
        run = self._run_repository.get(run_id)
        if run is None:
            raise NotFoundError(f"no evaluation run {run_id!r}")
        results = self._case_result_store.get(run.id) or []
        return run, results
