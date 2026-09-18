import pytest
from pydantic import ValidationError

from app.domain import GateDecision, GateStatus, RegressionSummary


def _decision(**overrides) -> GateDecision:
    defaults = {
        "run_id": "run-1",
        "dataset_version": "1.1.0",
        "provider": "deterministic",
        "model": "fixture-v1",
        "policy_id": "policy-1",
        "policy_version": "1.0.0",
        "status": GateStatus.PASS,
    }
    defaults.update(overrides)
    return GateDecision(**defaults)


def test_creates_pass_decision():
    decision = _decision(aggregate_metrics={"faithfulness": 0.95})

    assert decision.reasons == []
    assert decision.critical_failures == []
    assert decision.regression_summary is None
    assert decision.framework_errors == {}


def test_creates_block_decision_with_reasons():
    decision = _decision(
        status=GateStatus.BLOCK,
        reasons=["critical case case-7 failed groundedness"],
        critical_failures=["case-7"],
        aggregate_metrics={"faithfulness": 0.4},
    )

    assert decision.status == GateStatus.BLOCK
    assert "case-7" in decision.critical_failures


def test_rejects_invalid_status_value():
    with pytest.raises(ValidationError):
        _decision(status="maybe")


def test_rejects_blank_run_id():
    with pytest.raises(ValidationError):
        _decision(run_id="  ")


def test_framework_errors_records_infrastructure_failure_counts_separately_from_metrics():
    decision = _decision(
        status=GateStatus.WARN,
        aggregate_metrics={"ragas_faithfulness": 0.9},
        framework_errors={"ragas_context_recall": 2},
    )

    assert decision.aggregate_metrics == {"ragas_faithfulness": 0.9}
    assert decision.framework_errors == {"ragas_context_recall": 2}


def test_regression_summary_holds_deltas_and_new_recovered_failures():
    decision = _decision(
        status=GateStatus.BLOCK,
        baseline_version=3,
        regression_summary=RegressionSummary(
            baseline_version=3,
            pass_rate_delta=-0.1,
            metric_deltas={"ragas_faithfulness": -0.2},
            new_failures=["ragas_faithfulness"],
            recovered_failures=[],
        ),
    )

    assert decision.regression_summary.baseline_version == 3
    assert decision.regression_summary.new_failures == ["ragas_faithfulness"]
    assert decision.baseline_version == 3
