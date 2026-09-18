from datetime import UTC, datetime

from pydantic import BaseModel, Field, field_validator


class Baseline(BaseModel):
    """An approved snapshot of one evaluation run's aggregate results,
    against which future runs of the same dataset are compared for
    regressions (requirement #2/#3: versioned baselines, current-run vs
    approved-baseline comparison).

    `version` is a simple, monotonically increasing integer scoped to
    `dataset_name` (1, 2, 3, ...) - assigned by `BaselineRepository.approve`,
    never chosen by the caller, so baseline history for a dataset is always
    unambiguous and ordered.
    """

    id: str
    dataset_name: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    version: int = Field(ge=1)
    run_id: str = Field(min_length=1)
    pass_rate: float = Field(ge=0.0, le=1.0)
    aggregate_metrics: dict[str, float] = Field(default_factory=dict)
    approved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    approved_by: str | None = None
    notes: str | None = None

    @field_validator("dataset_name", "dataset_version", "run_id")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped
