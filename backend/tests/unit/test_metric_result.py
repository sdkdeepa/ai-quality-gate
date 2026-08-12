import math

import pytest
from pydantic import ValidationError

from app.domain import MetricResult


def test_creates_valid_metric_result():
    metric = MetricResult(
        metric_name="faithfulness",
        score=0.92,
        threshold=0.8,
        passed=True,
        framework="ragas",
    )

    assert metric.passed is True
    assert metric.explanation is None
    assert metric.metadata == {}


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_rejects_non_finite_score(value):
    with pytest.raises(ValidationError):
        MetricResult(
            metric_name="faithfulness",
            score=value,
            threshold=0.8,
            passed=False,
            framework="ragas",
        )


def test_rejects_blank_metric_name_or_framework():
    with pytest.raises(ValidationError):
        MetricResult(metric_name="  ", score=0.5, threshold=0.5, passed=True, framework="ragas")

    with pytest.raises(ValidationError):
        MetricResult(
            metric_name="faithfulness", score=0.5, threshold=0.5, passed=True, framework="  "
        )
