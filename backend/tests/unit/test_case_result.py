import pytest
from pydantic import ValidationError

from app.domain import CaseResult, MetricResult


def _metric(passed: bool) -> MetricResult:
    return MetricResult(
        metric_name="faithfulness", score=0.9, threshold=0.8, passed=passed, framework="ragas"
    )


def test_creates_valid_case_result():
    result = CaseResult(
        case_id="case-1",
        response="The refund window is 30 days.",
        retrieved_context=["Refunds are accepted within 30 days of purchase."],
        latency_ms=250.5,
        input_tokens=120,
        output_tokens=40,
        estimated_cost=0.0021,
        metric_results=[_metric(True)],
        passed=True,
    )

    assert result.critical_failure is False
    assert result.metric_results[0].passed is True


@pytest.mark.parametrize("field", ["latency_ms", "input_tokens", "output_tokens", "estimated_cost"])
def test_rejects_negative_numeric_fields(field):
    payload = {
        "case_id": "case-1",
        "response": "r",
        "latency_ms": 1.0,
        "input_tokens": 1,
        "output_tokens": 1,
        "estimated_cost": 0.0,
        "passed": True,
    }
    payload[field] = -1

    with pytest.raises(ValidationError):
        CaseResult(**payload)


def test_rejects_blank_case_id():
    with pytest.raises(ValidationError):
        CaseResult(
            case_id="   ",
            response="r",
            latency_ms=1.0,
            input_tokens=1,
            output_tokens=1,
            estimated_cost=0.0,
            passed=True,
        )
