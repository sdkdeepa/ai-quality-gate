from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    """Liveness check. Always returns 200 if the process is up."""
    return {"status": "ok"}


@router.get("/ready")
def ready(request: Request) -> JSONResponse:
    """Readiness check (Sprint 12 requirement: "health/readiness
    endpoints"). Distinct from `/health`: a process can be alive (serving
    HTTP at all) while a dependency it needs to actually do useful work is
    broken — an unwritable SQLite path, a corrupted Chroma store, a
    dataset directory that failed to load. `/health` can never catch
    that (it checks nothing); this endpoint runs each dependency's
    cheapest possible real read and reports 200 only if every one
    succeeds, 503 with the specific failures otherwise — so a deployment's
    orchestrator (Docker/Kubernetes/the docker-compose HEALTHCHECK) can
    tell "started" from "actually able to serve a real request" before
    routing traffic to this instance.
    """
    checks: dict[str, str] = {}
    healthy = True

    try:
        request.app.state.dataset_service.list_datasets()
        checks["datasets"] = "ok"
    except Exception as exc:  # noqa: BLE001 - report every failure, not just the first
        checks["datasets"] = f"error: {exc}"
        healthy = False

    try:
        request.app.state.policy_repository.list()
        checks["policy_store"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["policy_store"] = f"error: {exc}"
        healthy = False

    try:
        request.app.state.rag_vector_store.chunk_count()
        checks["rag_vector_store"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["rag_vector_store"] = f"error: {exc}"
        healthy = False

    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"status": "ready" if healthy else "not_ready", "checks": checks},
    )
