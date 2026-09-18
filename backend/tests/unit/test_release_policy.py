import pytest
from pydantic import ValidationError

from app.domain.release_policy import ReleasePolicy, RequiredMetricPolicy, default_policy


def test_default_policy_is_permissive():
    policy = default_policy()

    assert policy.required_metrics == []
    assert policy.min_pass_rate == 1.0
    assert policy.critical_case_action == "block"
    assert policy.latency_budget_ms is None
    assert policy.cost_budget_usd is None


def test_rejects_blank_name():
    with pytest.raises(ValidationError):
        ReleasePolicy(name="  ", version="1.0.0")


def test_rejects_blank_version():
    with pytest.raises(ValidationError):
        ReleasePolicy(name="p", version="  ")


def test_min_pass_rate_must_be_between_zero_and_one():
    with pytest.raises(ValidationError):
        ReleasePolicy(name="p", version="1.0.0", min_pass_rate=1.5)
    with pytest.raises(ValidationError):
        ReleasePolicy(name="p", version="1.0.0", min_pass_rate=-0.1)


def test_required_metric_policy_defaults_to_blocking():
    required = RequiredMetricPolicy(metric_name="ragas_faithfulness")

    assert required.on_missing == "block"
    assert required.on_infrastructure_failure == "block"
    assert required.min_score is None


def test_required_metric_policy_rejects_blank_metric_name():
    with pytest.raises(ValidationError):
        RequiredMetricPolicy(metric_name="  ")


def test_required_metric_min_score_must_be_between_zero_and_one():
    with pytest.raises(ValidationError):
        RequiredMetricPolicy(metric_name="x", min_score=1.5)


def test_policy_accepts_a_list_of_required_metrics():
    policy = ReleasePolicy(
        name="strict",
        version="2.0.0",
        required_metrics=[
            RequiredMetricPolicy(metric_name="exact_match", min_score=1.0),
            RequiredMetricPolicy(
                metric_name="ragas_faithfulness", min_score=0.8, on_missing="warn"
            ),
        ],
    )

    assert len(policy.required_metrics) == 2
    assert policy.required_metrics[1].on_missing == "warn"
