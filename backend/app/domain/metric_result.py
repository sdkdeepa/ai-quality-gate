import math
from typing import Any

from pydantic import BaseModel, Field, field_validator


class MetricResult(BaseModel):
    """A single normalized metric produced by an evaluation framework plugin."""

    metric_name: str = Field(min_length=1)
    score: float
    threshold: float
    passed: bool
    framework: str = Field(min_length=1)
    explanation: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("score", "threshold")
    @classmethod
    def _finite(cls, value: float) -> float:
        if math.isnan(value) or math.isinf(value):
            raise ValueError("must be a finite number")
        return value

    @field_validator("metric_name", "framework")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped
