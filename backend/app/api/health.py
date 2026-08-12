from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    """Liveness check. Always returns 200 if the process is up."""
    return {"status": "ok"}
