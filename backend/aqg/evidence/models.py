"""Quality-evidence model (M1).

Every input the gate reads (JUnit XML from pytest, Vitest and Playwright in M2,
existing LLM evaluation runs in M3) is converted into an ``EvidenceRun``: one
run made of ``CheckEvidence`` items, each with an explicit status.

Rules this model enforces:

- A check's status is one of passed, failed, skipped or error, stated
  explicitly. Nothing is inferred. "Missing" is not a status: the policy (M4)
  reports it when a required id or pattern matches no check.
- Check ids must be non-blank and unique within a run, so one test can't hide
  behind another with the same id.
- Unknown fields and unknown schema versions are rejected, so a file written by
  a newer or different tool is never half-read.
- A run with zero checks is valid here on purpose: the policy turns it into
  BLOCK ("nothing ran") instead of the importer silently dropping it.

This module depends only on Pydantic and the standard library.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

SCHEMA_VERSION = "1"


# Non-blank, with no leading or trailing whitespace. Expressed as a pattern (not
# a Python validator) so schema.json carries the same rule for other tools.
NonBlankStr = Annotated[str, StringConstraints(pattern=r"^\S(?:[\s\S]*\S)?$")]
FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]


class CheckStatus(StrEnum):
    """The outcome of one check. Only ``passed`` ever counts as passed."""

    PASSED = "passed"
    FAILED = "failed"  # ran, and the assertion failed
    SKIPPED = "skipped"  # did not run
    ERROR = "error"  # could not run properly: crash, setup failure, infrastructure


class CheckSource(StrEnum):
    """The tool that produced a check."""

    PYTEST = "pytest"
    VITEST = "vitest"
    PLAYWRIGHT = "playwright"
    LLM = "llm"


class InputFormat(StrEnum):
    """The kind of input a run was built from."""

    JUNIT = "junit"
    LLM = "llm"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CheckEvidence(_Model):
    """One check (a test case, or one LLM metric on one case) and its outcome."""

    id: NonBlankStr = Field(description="Stable id, the same across runs.")
    name: NonBlankStr = Field(description="Human-readable name.")
    suite: NonBlankStr | None = Field(default=None, description="Suite or group label.")
    source: CheckSource
    status: CheckStatus
    duration_ms: FiniteFloat | None = Field(default=None, ge=0)
    message: str | None = Field(default=None, description="Failure, error or skip message.")
    metrics: dict[NonBlankStr, FiniteFloat] = Field(
        default_factory=dict, description="Optional numeric results, e.g. LLM metric scores."
    )
    tags: list[NonBlankStr] = Field(default_factory=list)


class EvidenceInput(_Model):
    """Where part of a run's evidence came from (a result file, or an LLM run)."""

    format: InputFormat
    path: NonBlankStr = Field(description="Result file path, or the source run id for llm.")


class EvidenceRun(_Model):
    """All the evidence for one gate decision."""

    schema_version: Literal["1"] = SCHEMA_VERSION
    project: NonBlankStr
    version: NonBlankStr | None = None
    commit: NonBlankStr | None = None
    created_at: AwareDatetime
    inputs: list[EvidenceInput] = Field(default_factory=list)
    checks: list[CheckEvidence] = Field(
        default_factory=list,
        description="Check ids must be unique within a run. An empty list is valid; "
        "the policy treats it as BLOCK.",
    )

    @model_validator(mode="after")
    def _unique_check_ids(self) -> EvidenceRun:
        seen: set[str] = set()
        duplicates: list[str] = []
        for check in self.checks:
            if check.id in seen and check.id not in duplicates:
                duplicates.append(check.id)
            seen.add(check.id)
        if duplicates:
            raise ValueError(f"duplicate check ids: {', '.join(duplicates)}")
        return self


def evidence_run_json_schema() -> dict[str, Any]:
    """The JSON Schema for ``EvidenceRun``, as saved in ``schema.json``."""
    return EvidenceRun.model_json_schema()
