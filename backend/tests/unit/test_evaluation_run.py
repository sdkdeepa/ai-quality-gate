from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.domain import EvaluationRun, RunStatus


def test_creates_run_with_defaults():
    run = EvaluationRun(dataset_version="v1.0.0", provider="deterministic", model="stub-model")

    assert run.id
    assert run.status == RunStatus.PENDING
    assert run.completed_at is None


def test_rejects_completed_before_started():
    started = datetime.now(UTC)
    completed = started - timedelta(minutes=5)

    with pytest.raises(ValidationError):
        EvaluationRun(
            dataset_version="v1.0.0",
            provider="deterministic",
            model="stub-model",
            started_at=started,
            completed_at=completed,
        )


def test_accepts_completed_after_started():
    started = datetime.now(UTC)
    completed = started + timedelta(minutes=5)

    run = EvaluationRun(
        dataset_version="v1.0.0",
        provider="deterministic",
        model="stub-model",
        started_at=started,
        completed_at=completed,
        status=RunStatus.COMPLETED,
    )

    assert run.status == RunStatus.COMPLETED


def test_rejects_blank_dataset_version():
    with pytest.raises(ValidationError):
        EvaluationRun(dataset_version="  ", provider="deterministic", model="stub-model")
