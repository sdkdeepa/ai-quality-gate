from pydantic import BaseModel, Field

from app.domain.evaluation_case import EvaluationCase


class EvaluationInput(BaseModel):
    """What the system under test produced for a case, ready to be scored by evaluators."""

    case: EvaluationCase
    response: str
    retrieved_context: list[str] = Field(default_factory=list)
    latency_ms: float = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    estimated_cost: float = Field(ge=0)


class FixtureResponse(BaseModel):
    """A pre-recorded, deterministic system-under-test response.

    Used to drive evaluation without a live model provider (none exists yet).
    """

    response: str
    retrieved_context: list[str] = Field(default_factory=list)
    latency_ms: float = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    estimated_cost: float = Field(ge=0)
