import time

from fastapi import FastAPI

from app.api import health, status
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestIDMiddleware
from app.domain import EvaluationCase, EvaluationRun
from app.repositories.in_memory import InMemoryRepository
from app.services.status_service import StatusService


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

    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(status.router, prefix=settings.api_v1_prefix)

    return app


app = create_app()
