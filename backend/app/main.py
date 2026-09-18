import time
from pathlib import Path

from fastapi import FastAPI

from app.api import datasets, evaluations, gate, health, rag, status
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestIDMiddleware
from app.domain import EvaluationCase, EvaluationRun, GoldenDataset
from app.domain.release_policy import default_policy
from app.evaluation.deepeval.factory import build_deepeval_evaluators
from app.evaluation.deterministic import DEFAULT_EVALUATORS
from app.evaluation.openai_evals.factory import build_openai_evals_evaluators
from app.evaluation.ragas.factory import build_ragas_evaluators
from app.evaluation.runner import EvaluationRunner
from app.observability.tracing import configure_tracing
from app.providers.factory import ProviderFactory
from app.rag.factory import build_retriever
from app.repositories.in_memory import InMemoryCaseResultStore, InMemoryRepository
from app.repositories.sqlite import BaselineRepository, GateDecisionRepository, PolicyRepository
from app.services.dataset_service import DatasetService
from app.services.evaluation_service import EvaluationService
from app.services.policy_service import PolicyService
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
    # Sprint 9 — Arize Phoenix Observability. Built once and threaded into
    # every instrumented component by constructor injection (not global
    # OTel state — see `configure_tracing`'s docstring for why). Disabled
    # or failed setup both fall back to OpenTelemetry's own no-op tracer,
    # so nothing below needs to branch on whether tracing actually worked.
    app.state.tracer = configure_tracing(
        enabled=settings.tracing_enabled,
        collector_endpoint=settings.phoenix_collector_endpoint,
        project_name=settings.phoenix_project_name,
    )
    # Sprint 5/6/7: the runner's evaluator list is the only thing that
    # changes to add a framework — DEFAULT_EVALUATORS (deterministic) plus
    # whatever build_ragas_evaluators(settings)/build_deepeval_evaluators(settings)/
    # build_openai_evals_evaluators(settings) return ([] when the
    # corresponding AQG_*_ENABLED is unset/false, the default for all
    # three). EvaluationRunner itself is unmodified since Sprint 4.
    evaluators = (
        list(DEFAULT_EVALUATORS)
        + build_ragas_evaluators(settings)
        + build_deepeval_evaluators(settings)
        + build_openai_evals_evaluators(settings)
    )
    app.state.evaluation_runner = EvaluationRunner(evaluators=evaluators, tracer=app.state.tracer)
    app.state.provider_factory = ProviderFactory(settings, app.state.dataset_service)
    app.state.evaluation_service = EvaluationService(
        dataset_service=app.state.dataset_service,
        runner=app.state.evaluation_runner,
        run_repository=app.state.run_repository,
        case_result_store=app.state.case_result_store,
        provider_factory=app.state.provider_factory,
    )

    app.state.rag_vector_store, app.state.rag_retriever = build_retriever(
        settings, BACKEND_ROOT, tracer=app.state.tracer
    )
    app.state.rag_service = RAGService(
        retriever=app.state.rag_retriever,
        vector_store=app.state.rag_vector_store,
        provider_factory=app.state.provider_factory,
        dataset_service=app.state.dataset_service,
        runner=app.state.evaluation_runner,
        rag_dataset_name=settings.rag_dataset_name,
    )

    # Sprint 8 — Release Policy Engine and Regression Baselines. SQLite-
    # backed (requirement #7); relative paths resolve against the backend
    # root, same convention as dataset_dir/rag_chroma_dir.
    policy_db_path = settings.policy_db_path
    if policy_db_path != ":memory:" and not Path(policy_db_path).is_absolute():
        policy_db_path = str(BACKEND_ROOT / policy_db_path)
    app.state.policy_repository = PolicyRepository(policy_db_path)
    app.state.baseline_repository = BaselineRepository(policy_db_path)
    app.state.gate_decision_repository = GateDecisionRepository(policy_db_path)
    # Seed a permissive default policy on first run only — never overwrite
    # whatever policy is already registered (e.g. from a prior process, or
    # one an operator configured via POST /api/v1/gate/policies).
    if app.state.policy_repository.get_active() is None:
        app.state.policy_repository.add(default_policy())
    app.state.policy_service = PolicyService(
        run_repository=app.state.run_repository,
        case_result_store=app.state.case_result_store,
        policy_repository=app.state.policy_repository,
        baseline_repository=app.state.baseline_repository,
        gate_decision_repository=app.state.gate_decision_repository,
    )

    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(status.router, prefix=settings.api_v1_prefix)
    app.include_router(datasets.router, prefix=settings.api_v1_prefix)
    app.include_router(evaluations.router, prefix=settings.api_v1_prefix)
    app.include_router(rag.router, prefix=settings.api_v1_prefix)
    app.include_router(gate.router, prefix=settings.api_v1_prefix)

    return app


app = create_app()
