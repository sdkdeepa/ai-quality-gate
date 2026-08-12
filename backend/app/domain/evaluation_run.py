from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.enums import RunStatus


class EvaluationRun(BaseModel):
    """A single execution of an evaluation dataset against a provider/model."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    dataset_version: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    status: RunStatus = RunStatus.PENDING

    @field_validator("dataset_version", "provider", "model")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @model_validator(mode="after")
    def _completed_at_after_started_at(self) -> "EvaluationRun":
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("completed_at must not be before started_at")
        return self
