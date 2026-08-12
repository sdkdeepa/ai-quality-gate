from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from app.domain.enums import ExpectedBehavior


class EvaluationCase(BaseModel):
    """A single golden-dataset case: an input plus the expectations used to grade it."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = Field(min_length=1)
    category: str = Field(min_length=1)
    query: str = Field(min_length=1)
    expected_answer: str | None = None
    expected_behavior: ExpectedBehavior = ExpectedBehavior.ANSWER
    reference_context: list[str] = Field(default_factory=list)
    critical: bool = False
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name", "category", "query")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @field_validator("tags")
    @classmethod
    def _no_blank_tags(cls, tags: list[str]) -> list[str]:
        if any(not tag.strip() for tag in tags):
            raise ValueError("tags must not contain blank entries")
        return tags
