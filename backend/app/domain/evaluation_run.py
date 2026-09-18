from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.enums import RunStatus


class EvaluationRun(BaseModel):
    """A single execution of an evaluation dataset against a provider/model."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    # Sprint 8: needed to scope baseline lookups (`BaselineRepository.get_latest_for_dataset`)
    # — a GoldenDataset's identity is name+version together
    # (`GoldenDataset.id`), but only the version was recorded here through
    # Sprint 7. A real gap Sprint 8 exposes, not a redesign: `runner.py`
    # already has `dataset.name` in hand when constructing this.
    dataset_name: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    status: RunStatus = RunStatus.PENDING
    # Sprint 9: the OpenTelemetry trace id (32-hex-digit string) of this
    # run's root span, when tracing is enabled and configured successfully
    # — None otherwise (tracing disabled, or Phoenix/registration failed;
    # see `app/observability/tracing.py`). Requirement: "trace IDs
    # persisted with runs ... correlated to audit records" — a
    # `GateDecision` about this run copies it (see `PolicyService.decide`)
    # so a reader of either can jump straight to the other.
    trace_id: str | None = None

    @field_validator("dataset_name", "dataset_version", "provider", "model")
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
