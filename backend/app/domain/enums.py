from enum import StrEnum


class ExpectedBehavior(StrEnum):
    """What the system under test is expected to do for a given case."""

    ANSWER = "answer"
    REFUSE = "refuse"
    UNSUPPORTED = "unsupported"
    CLARIFY = "clarify"


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    # Sprint 12: at least one case's CaseResult.partial is True (a
    # framework infrastructure failure or this runner's own timeout/crash
    # isolation meant some configured check never produced a real score
    # for that case) — distinct from COMPLETED (every case's evaluation
    # ran to completion cleanly) and from FAILED (below), which this
    # runner has never actually set: nothing in the current design treats
    # an entire RUN as un-runnable rather than degraded, so FAILED remains
    # reserved for a future sprint's use, not retired.
    PARTIAL = "partial"
    FAILED = "failed"


class GateStatus(StrEnum):
    PASS = "pass"
    WARN = "warn"
    BLOCK = "block"
