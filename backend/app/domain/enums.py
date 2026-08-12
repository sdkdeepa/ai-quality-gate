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
    FAILED = "failed"


class GateStatus(StrEnum):
    PASS = "pass"
    WARN = "warn"
    BLOCK = "block"
