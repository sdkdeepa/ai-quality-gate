from pydantic import BaseModel, Field, field_validator

from app.domain.metric_result import MetricResult


class CaseResult(BaseModel):
    """The outcome of running one EvaluationCase through the system under test."""

    case_id: str = Field(min_length=1)
    response: str
    retrieved_context: list[str] = Field(default_factory=list)
    latency_ms: float = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    estimated_cost: float = Field(ge=0)
    metric_results: list[MetricResult] = Field(default_factory=list)
    passed: bool
    critical_failure: bool = False

    @field_validator("case_id")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped
