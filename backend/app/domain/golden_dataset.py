import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.domain.evaluation_case import EvaluationCase

_SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


class GoldenDataset(BaseModel):
    """A versioned, named collection of EvaluationCases used as a release gate's ground truth."""

    name: str = Field(min_length=1)
    version: str
    created_at: datetime
    description: str = Field(min_length=1)
    cases: list[EvaluationCase]

    @property
    def id(self) -> str:
        return f"{self.name}@{self.version}"

    @field_validator("name", "description")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @field_validator("version")
    @classmethod
    def _valid_semver(cls, value: str) -> str:
        if not _SEMVER_PATTERN.match(value):
            raise ValueError(f"version must be a semantic version X.Y.Z, got {value!r}")
        return value

    @field_validator("cases")
    @classmethod
    def _cases_non_empty_and_unique(cls, cases: list[EvaluationCase]) -> list[EvaluationCase]:
        if not cases:
            raise ValueError("dataset must contain at least one case")
        ids = [case.id for case in cases]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate case ids: {duplicates}")
        return cases


def semver_key(version: str) -> tuple[int, int, int]:
    """Sort key for X.Y.Z semantic version strings already validated by GoldenDataset."""
    major, minor, patch = version.split(".")
    return int(major), int(minor), int(patch)
