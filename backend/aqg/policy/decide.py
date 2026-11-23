"""Evidence gate decision (M4): an EvidenceRun plus an EvidencePolicy gives
PASS, WARN or BLOCK.

The server's ``PolicyEngine`` stays the decision maker for the server. This is
a second engine for evidence; ``tests/aqg/test_policy_parity.py`` checks that
both agree on the rules they share.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from aqg.evidence import CheckEvidence, CheckStatus, EvidenceRun
from aqg.importers.junit import FLAKY_TAG
from aqg.policy.models import (
    Action,
    CheckCounts,
    EvidenceDecision,
    EvidencePolicy,
    GateStatus,
)

MAX_IDS_IN_REASON = 5


def pattern_matcher(pattern: str) -> re.Pattern[str]:
    """Compile a required id or pattern. Only '*' and '?' are wildcards, so ids
    with brackets (pytest parameters such as ``test_x[a]``) match literally."""
    parts = []
    for char in pattern:
        if char == "*":
            parts.append(".*")
        elif char == "?":
            parts.append(".")
        else:
            parts.append(re.escape(char))
    return re.compile("".join(parts), re.DOTALL)


def _ids(checks: Sequence[CheckEvidence]) -> str:
    shown = ", ".join(c.id for c in checks[:MAX_IDS_IN_REASON])
    more = len(checks) - MAX_IDS_IN_REASON
    return f"{shown} (+{more} more)" if more > 0 else shown


def _count(checks: Sequence[CheckEvidence], kind: str = "") -> str:
    noun = "check" if len(checks) == 1 else "checks"
    return f"{len(checks)} {kind} {noun}" if kind else f"{len(checks)} {noun}"


class _Reasons:
    def __init__(self) -> None:
        self.blocking: list[str] = []
        self.warnings: list[str] = []

    def add(self, action: Action, reason: str) -> None:
        if action is Action.BLOCK:
            self.blocking.append(reason)
        elif action is Action.WARN:
            self.warnings.append(reason)
        # Action.IGNORE: deliberately not recorded.

    def by_status(
        self, action: Action, checks: Sequence[CheckEvidence], kind: str, what: str
    ) -> None:
        if checks:
            self.add(action, f"{_count(checks, kind)} {what}: {_ids(checks)}")


def _counts(checks: Sequence[CheckEvidence]) -> CheckCounts:
    def n(status: CheckStatus) -> int:
        return sum(1 for c in checks if c.status is status)

    return CheckCounts(
        total=len(checks),
        passed=n(CheckStatus.PASSED),
        failed=n(CheckStatus.FAILED),
        skipped=n(CheckStatus.SKIPPED),
        error=n(CheckStatus.ERROR),
        flaky=sum(1 for c in checks if c.status is CheckStatus.PASSED and FLAKY_TAG in c.tags),
    )


def decide(
    run: EvidenceRun,
    policy: EvidencePolicy,
    *,
    input_blockers: Iterable[str] = (),
) -> EvidenceDecision:
    """Decide PASS, WARN or BLOCK.

    ``input_blockers`` are problems found while reading the evidence (for
    example ``JUnitImport.blockers``: an empty report, or fewer tests than
    min_checks). Each one blocks.
    """
    reasons = _Reasons()
    checks = list(run.checks)
    counts = _counts(checks)

    for blocker in input_blockers:
        reasons.blocking.append(blocker)

    # Rules that can't be configured away (carried over from PolicyEngine).
    if not checks:
        reasons.blocking.append("no checks were found, so nothing ran")
    elif counts.passed + counts.failed == 0:
        reasons.blocking.append(
            f"none of the {counts.total} checks passed or failed: every check was "
            "skipped or errored, so nothing really ran"
        )

    # Required ids and patterns.
    matchers = [(p, pattern_matcher(p)) for p in policy.required]
    required_ids: set[str] = set()
    missing: list[str] = []
    for pattern, matcher in matchers:
        matched = {c.id for c in checks if matcher.fullmatch(c.id)}
        if not matched:
            missing.append(pattern)
        required_ids |= matched
    required = [c for c in checks if c.id in required_ids]
    optional = [c for c in checks if c.id not in required_ids]

    if missing:
        reasons.add(
            policy.on_missing,
            f"{len(missing)} required check pattern(s) matched no check: {', '.join(missing)}",
        )

    def having(group: Sequence[CheckEvidence], status: CheckStatus) -> list[CheckEvidence]:
        return [c for c in group if c.status is status]

    # A failed required check always blocks (as a required metric failing its
    # own quality bar does in PolicyEngine).
    reasons.by_status(Action.BLOCK, having(required, CheckStatus.FAILED), "required", "failed")
    reasons.by_status(policy.on_error, having(required, CheckStatus.ERROR), "required", "errored")
    reasons.by_status(
        policy.on_skipped, having(required, CheckStatus.SKIPPED), "required", "skipped"
    )
    reasons.by_status(
        policy.on_optional_failed, having(optional, CheckStatus.FAILED), "optional", "failed"
    )
    reasons.by_status(
        policy.on_optional_error, having(optional, CheckStatus.ERROR), "optional", "errored"
    )
    reasons.by_status(
        policy.on_optional_skipped,
        having(optional, CheckStatus.SKIPPED),
        "optional",
        "skipped",
    )
    flaky = [c for c in checks if c.status is CheckStatus.PASSED and FLAKY_TAG in c.tags]
    if flaky:
        reasons.add(
            policy.on_flaky, f"{_count(flaky)} passed only after a retry (flaky): {_ids(flaky)}"
        )

    ran = counts.passed + counts.failed + counts.error
    pass_rate = counts.passed / ran if ran else None
    if policy.min_pass_rate is not None and pass_rate is not None:
        if pass_rate < policy.min_pass_rate:
            reasons.blocking.append(
                f"pass rate {pass_rate:.2%} is below the required minimum "
                f"{policy.min_pass_rate:.2%} ({counts.passed}/{ran} checks that ran passed)"
            )

    if reasons.blocking:
        status = GateStatus.BLOCK
    elif reasons.warnings:
        status = GateStatus.WARN
    else:
        status = GateStatus.PASS

    return EvidenceDecision(
        status=status,
        blocking=reasons.blocking,
        warnings=reasons.warnings,
        counts=counts,
        pass_rate=pass_rate,
        missing_required=missing,
        fail_on_warn=policy.fail_on_warn,
    )
