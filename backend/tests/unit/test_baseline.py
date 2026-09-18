import pytest
from pydantic import ValidationError

from app.domain.baseline import Baseline


def _baseline(**overrides) -> Baseline:
    defaults = {
        "id": "b1",
        "dataset_name": "support_bot",
        "dataset_version": "1.0.0",
        "version": 1,
        "run_id": "run-1",
        "pass_rate": 0.95,
        "aggregate_metrics": {"exact_match": 0.95},
    }
    defaults.update(overrides)
    return Baseline(**defaults)


def test_creates_baseline_with_defaults():
    baseline = _baseline()

    assert baseline.approved_by is None
    assert baseline.notes is None
    assert baseline.approved_at is not None


def test_rejects_blank_dataset_name():
    with pytest.raises(ValidationError):
        _baseline(dataset_name="  ")


def test_rejects_version_below_one():
    with pytest.raises(ValidationError):
        _baseline(version=0)


def test_pass_rate_must_be_between_zero_and_one():
    with pytest.raises(ValidationError):
        _baseline(pass_rate=1.5)


def test_accepts_optional_approver_and_notes():
    baseline = _baseline(approved_by="deepa", notes="approved after manual review")

    assert baseline.approved_by == "deepa"
    assert baseline.notes == "approved after manual review"
