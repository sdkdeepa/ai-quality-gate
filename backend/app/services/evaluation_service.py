from app.core.exceptions import NotFoundError
from app.domain.case_result import CaseResult
from app.domain.evaluation_run import EvaluationRun
from app.evaluation.runner import EvaluationRunner
from app.providers.factory import ProviderFactory
from app.repositories.in_memory import InMemoryCaseResultStore, InMemoryRepository
from app.services.dataset_service import DatasetService


class EvaluationService:
    """Orchestrates an evaluation run: resolve dataset, build the requested provider,
    run, persist."""

    def __init__(
        self,
        dataset_service: DatasetService,
        runner: EvaluationRunner,
        run_repository: InMemoryRepository[EvaluationRun],
        case_result_store: InMemoryCaseResultStore,
        provider_factory: ProviderFactory,
    ) -> None:
        self._dataset_service = dataset_service
        self._runner = runner
        self._run_repository = run_repository
        self._case_result_store = case_result_store
        self._provider_factory = provider_factory

    def run(
        self,
        dataset_name: str,
        dataset_version: str | None = None,
        provider_name: str = "deterministic",
        frameworks: set[str] | None = None,
    ) -> EvaluationRun:
        dataset = self._dataset_service.get_dataset(dataset_name, dataset_version)
        provider = self._provider_factory.create(provider_name, dataset=dataset)
        run, case_results = self._runner.run_with_provider(dataset, provider, frameworks=frameworks)
        self._run_repository.add(run)
        self._case_result_store.save(run.id, case_results)
        return run

    def get_run(self, run_id: str) -> tuple[EvaluationRun, list[CaseResult]]:
        run = self._run_repository.get(run_id)
        if run is None:
            raise NotFoundError(f"no evaluation run {run_id!r}")
        results = self._case_result_store.get(run.id) or []
        return run, results

    def list_runs(self) -> list[EvaluationRun]:
        """Sprint 10: the dashboard's "Evaluation Runs" view needs a list
        endpoint that never existed through Sprint 1-9 (only "run" and
        "inspect one run" did — see PROJECT_STATE.md's prior outstanding
        work). `InMemoryRepository[T]` already implements `.list()`; this
        was purely a missing API-layer method, not a missing capability."""
        return self._run_repository.list()
