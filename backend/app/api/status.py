from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_status_service
from app.services.status_service import StatusService

router = APIRouter(tags=["status"])


@router.get("/status")
def get_status(status_service: Annotated[StatusService, Depends(get_status_service)]) -> dict:
    """Application status: version, environment, uptime, and repository counts."""
    return status_service.get_status()
