from fastapi import Request

from app.services.dataset_service import DatasetService
from app.services.evaluation_service import EvaluationService
from app.services.status_service import StatusService


def get_status_service(request: Request) -> StatusService:
    return request.app.state.status_service


def get_dataset_service(request: Request) -> DatasetService:
    return request.app.state.dataset_service


def get_evaluation_service(request: Request) -> EvaluationService:
    return request.app.state.evaluation_service
