from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_dataset_service
from app.domain.golden_dataset import GoldenDataset
from app.services.dataset_service import DatasetService

router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.get("")
def list_datasets(
    dataset_service: Annotated[DatasetService, Depends(get_dataset_service)],
) -> list[dict]:
    """Summary of every loaded dataset (all versions), without the full case list."""
    return [
        {
            "name": dataset.name,
            "version": dataset.version,
            "description": dataset.description,
            "created_at": dataset.created_at,
            "case_count": len(dataset.cases),
        }
        for dataset in dataset_service.list_datasets()
    ]


@router.get("/{name}/{version}")
def get_dataset(
    name: str,
    version: str,
    dataset_service: Annotated[DatasetService, Depends(get_dataset_service)],
) -> GoldenDataset:
    """Full dataset detail including all cases. Use version="latest" for the newest version."""
    return dataset_service.get_dataset(name, version)
