import time

from app.core.config import Settings
from app.domain import EvaluationCase, EvaluationRun
from app.repositories.in_memory import InMemoryRepository


class StatusService:
    """Assembles the application status payload from config and repository state."""

    def __init__(
        self,
        settings: Settings,
        case_repository: InMemoryRepository[EvaluationCase],
        run_repository: InMemoryRepository[EvaluationRun],
        started_at: float,
    ) -> None:
        self._settings = settings
        self._case_repository = case_repository
        self._run_repository = run_repository
        self._started_at = started_at

    def get_status(self) -> dict:
        return {
            "status": "ok",
            "app_name": self._settings.app_name,
            "version": self._settings.version,
            "environment": self._settings.environment,
            "uptime_seconds": round(time.monotonic() - self._started_at, 3),
            "counts": {
                "evaluation_cases": self._case_repository.count(),
                "evaluation_runs": self._run_repository.count(),
            },
        }
