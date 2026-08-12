from fastapi import Request

from app.services.status_service import StatusService


def get_status_service(request: Request) -> StatusService:
    return request.app.state.status_service
