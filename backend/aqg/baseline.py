"""Approved baselines and regression reports (M5).

A baseline is an approved run, saved as a JSON file in the project's repo
(for example ``quality/baseline.json``) and changed only through an ordinary
reviewed PR. It is never "the latest run".

Approving
    Only a run whose decision was PASS can be approved, unless ``allow_warn``
    is set. A BLOCK run is never approved.

Comparing a run with its baseline lists, separately:
    new_failures        in the baseline and passing there; failed or error now
    new_failing         not in the baseline at all; failed or error now
    removed             in the baseline; missing now
    skipped_required    required, ran in the baseline (not skipped); skipped now
    renamed             confirmed renames from a ``renames`` map (old id -> new id),
                        compared as one test
    possible_renames    one removed and one added test with the same
                        ``suite::classname``; still counted as removed and added
                        until confirmed
    recovered           failed or error in the baseline; passing now (informational)
    added               not in the baseline; passing now (informational)

``RegressionPolicy`` decides what blocks, and ``apply_regressions`` merges the
result into the M4 decision. A missing, corrupt or mismatched baseline raises
``BaselineError``: it is never a silent pass.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

from aqg.evidence import CheckStatus, EvidenceRun
from aqg.evidence.models import NonBlankStr
from aqg.importers.junit import FLAKY_TAG
from aqg.policy import Action, CheckCounts, EvidenceDecision, GateStatus, pattern_matcher

BASELINE_SCHEMA_VERSION = "1"
_FAILING = (CheckStatus.FAILED, CheckStatus.ERROR)
MAX_IDS_IN_REASON = 5


class BaselineError(Exception):
    """The baseline can't be used: missing, corrupt, mismatched, or not approvable."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Baseline(_Model):
    """An approved run, as stored in the baseline file."""

    schema_version: Literal["1"] = BASELINE_SCHEMA_VERSION
    project: NonBlankStr
    version: NonBlankStr | None = None
    commit: NonBlankStr | None = None
    report: NonBlankStr = Field(description="The report the approved run came from.")
    decision: Literal[GateStatus.PASS, GateStatus.WARN]
    approved_by: NonBlankStr
    approved_at: AwareDatetime
    counts: CheckCounts
    checks: dict[NonBlankStr, CheckStatus]
    flaky: list[NonBlankStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistent(self) -> Baseline:
        statuses = list(self.checks.values())

        def n(status: CheckStatus) -> int:
            return sum(1 for s in statuses if s is status)

        expected = CheckCounts(
            total=len(statuses),
            passed=n(CheckStatus.PASSED),
            failed=n(CheckStatus.FAILED),
            skipped=n(CheckStatus.SKIPPED),
            error=n(CheckStatus.ERROR),
            flaky=len(self.flaky),
        )
        if self.counts != expected:
            raise ValueError(
                f"counts {self.counts.model_dump()} don't match the checks "
                f"{expected.model_dump()}; the file was edited by hand or is incomplete"
            )
        if not self.checks:
            raise ValueError("a baseline must contain at least one check")
        not_passed = [i for i in self.flaky if self.checks.get(i) is not CheckStatus.PASSED]
        if not_passed:
            raise ValueError(f"flaky ids must be passed checks: {', '.join(not_passed)}")
        return self


# --- approving, saving and loading ----------------------------------------------


def approve_baseline(
    run: EvidenceRun,
    decision: EvidenceDecision,
    *,
    approved_by: str,
    report: str,
    approved_at: datetime | None = None,
    allow_warn: bool = False,
) -> Baseline:
    """Turn an approved run into a baseline. Raises ``BaselineError`` unless the
    decision was PASS (or WARN with ``allow_warn``)."""
    if decision.status is GateStatus.BLOCK:
        raise BaselineError("a BLOCK run can't be approved as a baseline")
    if decision.status is GateStatus.WARN and not allow_warn:
        raise BaselineError(
            "this run's decision was WARN; approve it only on purpose, with allow_warn "
            "(--allow-warn)"
        )
    counts = decision.counts
    flaky = sorted(
        c.id for c in run.checks if c.status is CheckStatus.PASSED and FLAKY_TAG in c.tags
    )
    try:
        return Baseline(
            project=run.project,
            version=run.version,
            commit=run.commit,
            report=report,
            decision=decision.status,
            approved_by=approved_by,
            approved_at=approved_at or datetime.now(UTC),
            counts=counts,
            checks={c.id: c.status for c in run.checks},
            flaky=flaky,
        )
    except ValidationError as exc:
        raise BaselineError(f"can't approve this run: {exc}") from exc


def baseline_json(baseline: Baseline) -> str:
    """Stable JSON (sorted keys, two-space indent) so baseline PRs diff cleanly."""
    data = baseline.model_dump(mode="json")
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_baseline(path: str | Path, baseline: Baseline) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(baseline_json(baseline), encoding="utf-8")


def load_baseline(path: str | Path) -> Baseline:
    """Read a baseline file. Raises ``BaselineError`` with a clear message if it is
    missing, unreadable, not JSON, or doesn't match the baseline format."""
    path = Path(path)
    if not path.is_file():
        raise BaselineError(
            f"{path}: baseline file not found. Approve a PASS run first "
            "(aqg baseline approve), then commit the file."
        )
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise BaselineError(f"{path}: baseline file can't be read ({exc})") from exc
    if not text.strip():
        raise BaselineError(f"{path}: baseline file is empty")
    try:
        return Baseline.model_validate_json(text)
    except ValidationError as exc:
        raise BaselineError(f"{path}: not a valid baseline file: {exc}") from exc


# --- comparing a run with its baseline -------------------------------------------


class Rename(_Model):
    old: NonBlankStr
    new: NonBlankStr


class RegressionReport(_Model):
    new_failures: list[str] = Field(default_factory=list)
    new_failing: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    removed_required: list[str] = Field(default_factory=list)
    skipped_required: list[str] = Field(default_factory=list)
    renamed: list[Rename] = Field(default_factory=list)
    possible_renames: list[Rename] = Field(default_factory=list)
    recovered: list[str] = Field(default_factory=list)
    added: list[str] = Field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return any(getattr(self, name) for name in type(self).model_fields)


def _group(check_id: str) -> str:
    """``suite::classname`` of a ``suite::classname::name`` id."""
    return check_id.rsplit("::", 1)[0] if "::" in check_id else ""


def compare_to_baseline(
    run: EvidenceRun,
    baseline: Baseline,
    *,
    required: Sequence[str] = (),
    renames: Mapping[str, str] | None = None,
) -> RegressionReport:
    """Compare a run with its approved baseline.

    ``required`` takes the same ids and patterns as ``EvidencePolicy.required``.
    ``renames`` maps an old (baseline) id to its new id. Raises
    ``BaselineError`` for a baseline from another project or a rename that
    can't apply.
    """
    if run.project != baseline.project:
        raise BaselineError(
            f"the baseline is for project {baseline.project!r}, not {run.project!r}"
        )
    renames = dict(renames or {})
    current = {c.id: c.status for c in run.checks}
    for old, new in renames.items():
        if old not in baseline.checks:
            raise BaselineError(f"rename {old!r} -> {new!r}: {old!r} is not in the baseline")
        if new in baseline.checks:
            raise BaselineError(f"rename {old!r} -> {new!r}: {new!r} is already in the baseline")
        if old in current:
            raise BaselineError(f"rename {old!r} -> {new!r}: {old!r} still exists in this run")
    if len(set(renames.values())) != len(renames):
        raise BaselineError("two renames point to the same new id")

    matchers = [pattern_matcher(p) for p in required]

    def is_required(check_id: str) -> bool:
        return any(m.fullmatch(check_id) for m in matchers)

    renamed = [Rename(old=o, new=n) for o, n in sorted(renames.items()) if n in current]
    to_baseline_id = {r.new: r.old for r in renamed}  # current id -> baseline id
    seen_baseline: set[str] = set()

    new_failures, new_failing, skipped_required, recovered, added = [], [], [], [], []
    for check_id, status in current.items():
        baseline_id = to_baseline_id.get(check_id, check_id)
        before = baseline.checks.get(baseline_id)
        if before is None:
            if status in _FAILING:
                new_failing.append(check_id)
            elif status is CheckStatus.PASSED:
                added.append(check_id)
            continue
        seen_baseline.add(baseline_id)
        if before is CheckStatus.PASSED and status in _FAILING:
            new_failures.append(check_id)
        elif before in _FAILING and status is CheckStatus.PASSED:
            recovered.append(check_id)
        if (
            status is CheckStatus.SKIPPED
            and before is not CheckStatus.SKIPPED
            and (is_required(check_id) or is_required(baseline_id))
        ):
            skipped_required.append(check_id)

    removed = sorted(set(baseline.checks) - seen_baseline)
    removed_required = [i for i in removed if is_required(i)]
    new_ids = [i for i in current if to_baseline_id.get(i, i) not in baseline.checks]

    possible = []
    for group in sorted({_group(i) for i in removed}):
        gone = [i for i in removed if _group(i) == group]
        came = [i for i in new_ids if _group(i) == group]
        if len(gone) == 1 and len(came) == 1:
            possible.append(Rename(old=gone[0], new=came[0]))

    return RegressionReport(
        new_failures=sorted(new_failures),
        new_failing=sorted(new_failing),
        removed=removed,
        removed_required=removed_required,
        skipped_required=sorted(skipped_required),
        renamed=renamed,
        possible_renames=possible,
        recovered=sorted(recovered),
        added=sorted(added),
    )


# --- what blocks ---------------------------------------------------------------------


class RegressionPolicy(_Model):
    """What each kind of regression causes. Defaults follow the plan."""

    on_new_failure: Action = Action.BLOCK
    on_new_failing: Action = Action.BLOCK
    on_skipped_required: Action = Action.BLOCK
    on_removed_required: Action = Action.BLOCK
    on_removed: Action = Action.WARN  # removed tests that weren't required
    on_possible_rename: Action = Action.WARN


def _ids(ids: Sequence[str]) -> str:
    shown = ", ".join(ids[:MAX_IDS_IN_REASON])
    more = len(ids) - MAX_IDS_IN_REASON
    return f"{shown} (+{more} more)" if more > 0 else shown


def regression_reasons(
    report: RegressionReport, policy: RegressionPolicy
) -> tuple[list[str], list[str]]:
    """(blocking, warnings) for a regression report."""
    blocking: list[str] = []
    warnings: list[str] = []

    def add(action: Action, ids: Sequence[str], what: str) -> None:
        if not ids:
            return
        reason = f"{len(ids)} {what} since the baseline: {_ids(list(ids))}"
        if action is Action.BLOCK:
            blocking.append(reason)
        elif action is Action.WARN:
            warnings.append(reason)

    removed_optional = [i for i in report.removed if i not in report.removed_required]
    add(policy.on_new_failure, report.new_failures, "check(s) newly failing")
    add(policy.on_new_failing, report.new_failing, "new check(s) failing")
    add(policy.on_skipped_required, report.skipped_required, "required check(s) now skipped")
    add(policy.on_removed_required, report.removed_required, "required check(s) removed")
    add(policy.on_removed, removed_optional, "check(s) removed")
    if report.possible_renames:
        pairs = [f"{r.old} -> {r.new}" for r in report.possible_renames]
        reason = (
            f"{len(pairs)} possible rename(s); confirm in renames: to compare them as one "
            f"test: {_ids(pairs)}"
        )
        if policy.on_possible_rename is Action.BLOCK:
            blocking.append(reason)
        elif policy.on_possible_rename is Action.WARN:
            warnings.append(reason)
    return blocking, warnings


def apply_regressions(
    decision: EvidenceDecision, report: RegressionReport, policy: RegressionPolicy
) -> EvidenceDecision:
    """The M4 decision with the regression reasons added and the status updated."""
    blocking, warnings = regression_reasons(report, policy)
    all_blocking = [*decision.blocking, *blocking]
    all_warnings = [*decision.warnings, *warnings]
    if all_blocking:
        status = GateStatus.BLOCK
    elif all_warnings:
        status = GateStatus.WARN
    else:
        status = GateStatus.PASS
    return decision.model_copy(
        update={"status": status, "blocking": all_blocking, "warnings": all_warnings}
    )
