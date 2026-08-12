import pytest
from pydantic import ValidationError

from app.domain import GateDecision, GateStatus


def test_creates_pass_decision():
    decision = GateDecision(status=GateStatus.PASS, aggregate_metrics={"faithfulness": 0.95})

    assert decision.reasons == []
    assert decision.critical_failures == []
    assert decision.regression_summary is None


def test_creates_block_decision_with_reasons():
    decision = GateDecision(
        status=GateStatus.BLOCK,
        reasons=["critical case case-7 failed groundedness"],
        critical_failures=["case-7"],
        aggregate_metrics={"faithfulness": 0.4},
    )

    assert decision.status == GateStatus.BLOCK
    assert "case-7" in decision.critical_failures


def test_rejects_invalid_status_value():
    with pytest.raises(ValidationError):
        GateDecision(status="maybe")
