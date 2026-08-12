from typing import Any

from pydantic import BaseModel, Field

from app.domain.enums import GateStatus


class GateDecision(BaseModel):
    """The auditable release decision produced by the Quality Gate's own policy layer.

    This is deliberately independent of any evaluation framework: frameworks only
    ever produce MetricResult signals, never a decision.
    """

    status: GateStatus
    reasons: list[str] = Field(default_factory=list)
    aggregate_metrics: dict[str, float] = Field(default_factory=dict)
    critical_failures: list[str] = Field(default_factory=list)
    regression_summary: dict[str, Any] | None = None
