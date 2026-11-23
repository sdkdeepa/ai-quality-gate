"""Evidence policy and gate decision models (M4).

The policy says which checks are required and what each outcome causes. The
decision is PASS, WARN or BLOCK with the reasons and the counts behind it.

Status table (from the plan; required/optional defaults):
    passed              no reason needed
    passed, flaky       on_flaky                       warn
    failed              required: always BLOCK         optional: on_optional_failed (block)
    skipped             required: on_skipped (block)   optional: on_optional_skipped (warn)
    error               required: on_error (block)     optional: on_optional_error (block)
    missing             required: on_missing (block)   (not applicable to optional checks)

"Missing" is not a check status: it is reported when a required id or pattern
matches no check. Two rules can't be configured away: a run with no checks, or
with no check that passed or failed, is always BLOCK.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from aqg.evidence.models import NonBlankStr


class GateStatus(StrEnum):
    """The same values as the server's ``app.domain.enums.GateStatus``."""

    PASS = "pass"
    WARN = "warn"
    BLOCK = "block"


class Action(StrEnum):
    BLOCK = "block"
    WARN = "warn"
    IGNORE = "ignore"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidencePolicy(_Model):
    """What the evidence must show for a release to pass."""

    required: list[NonBlankStr] = Field(
        default_factory=list,
        description="Check ids or patterns. '*' matches any text and '?' one character; "
        "everything else, including '[' and ']', is literal.",
    )
    on_missing: Action = Action.BLOCK
    on_skipped: Action = Action.BLOCK
    on_error: Action = Action.BLOCK
    on_optional_skipped: Action = Action.WARN
    on_optional_failed: Action = Action.BLOCK
    on_optional_error: Action = Action.BLOCK
    on_flaky: Action = Action.WARN
    min_pass_rate: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Minimum passed / (passed + failed + error). Skipped checks are left out; "
        "the skip rules cover them.",
    )
    fail_on_warn: bool = False


class CheckCounts(_Model):
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    error: int = 0
    flaky: int = 0  # included in passed


class EvidenceDecision(_Model):
    status: GateStatus
    blocking: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    counts: CheckCounts
    pass_rate: float | None = Field(
        default=None, description="None when no check passed, failed or errored."
    )
    missing_required: list[str] = Field(default_factory=list)
    fail_on_warn: bool = False

    @property
    def reasons(self) -> list[str]:
        """Blocking reasons first, then warnings."""
        return [*self.blocking, *self.warnings]

    @property
    def fails_ci(self) -> bool:
        """BLOCK always fails CI; WARN only when fail_on_warn is on."""
        return self.status is GateStatus.BLOCK or (
            self.status is GateStatus.WARN and self.fail_on_warn
        )
