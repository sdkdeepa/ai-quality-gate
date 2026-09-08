import time
from pathlib import Path

from fastapi import FastAPI

from app.api import datasets, evaluations, health, rag, status
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestIDMiddleware
from app.domain import EvaluationCase, EvaluationRun, GoldenDataset
from app.evaluation.runner import EvaluationRunner
from app.providers.factory import ProviderFactory
from app.rag.factory import build_retriever
from app.repositories.in_memory import InMemoryCaseResultStore, InMemoryRepository
from app.services.dataset_service import DatasetService
from app.services.evaluation_service import EvaluationService
from app.services.rag_service import RAGService
from app.services.status_service import StatusService

BACKEND_ROOT = Path(__file__).resolve().parent.parent


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title=settings.app_name, version=settings.version)

    app.state.settings = settings
    app.state.case_repository = InMemoryRepository[EvaluationCase]()
    app.state.run_repository = InMemoryRepository[EvaluationRun]()
    app.state.status_service = StatusService(
        settings=settings,
        case_repository=app.state.case_repository,
        run_repository=app.state.run_repository,
        started_at=time.monotonic(),
    )

    dataset_dir = Path(settings.dataset_dir)
    if not dataset_dir.is_absolute():
        dataset_dir = BACKEND_ROOT / dataset_dir
    app.state.dataset_repository = InMemoryRepository[GoldenDataset]()
    app.state.dataset_service = DatasetService(dataset_dir, app.state.dataset_repository)
    app.state.dataset_service.load_all()

    app.state.case_result_store = InMemoryCaseResultStore()
    app.state.evaluation_runner = EvaluationRunner()
    app.state.provider_factory = ProviderFactory(settings, app.state.dataset_service)
    app.state.evaluation_service = EvaluationService(
        dataset_service=app.state.dataset_service,
        runner=app.state.evaluation_runner,
        run_repository=app.state.run_repository,
        case_result_store=app.state.case_result_store,
        provider_factory=app.state.provider_factory,
    )

    app.state.rag_vector_store, app.state.rag_retriever = build_retriever(settings, BACKEND_ROOT)
    app.state.rag_service = RAGService(
        retriever=app.state.rag_retriever,
        vector_store=app.state.rag_vector_store,
        provider_factory=app.state.provider_factory,
        dataset_service=app.state.dataset_service,
        runner=app.state.evaluation_runner,
        rag_dataset_name=settings.rag_dataset_name,
    )

    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(status.router, prefix=settings.api_v1_prefix)
    app.include_router(datasets.router, prefix=settings.api_v1_prefix)
    app.include_router(evaluations.router, prefix=settings.api_v1_prefix)
    app.include_router(rag.router, prefix=settings.api_v1_prefix)

    return app


app = create_app()
