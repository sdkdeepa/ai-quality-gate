from pathlib import Path

import pytest

from app.domain.golden_dataset import GoldenDataset
from app.evaluation.runner import EvaluationRunner
from app.repositories.in_memory import InMemoryRepository
from app.services.dataset_service import DatasetService

DATASET_DIR = Path(__file__).resolve().parents[2] / "datasets"

CRITICAL_CASE_IDS = {"ans-005", "uns-002", "ref-001", "str-002", "ret-002", "neg-001"}
EXPECTED_CRITICAL_FAILURES = {"str-002", "neg-001"}


@pytest.fixture(scope="module")
def seed_results():
    service = DatasetService(DATASET_DIR, InMemoryRepository[GoldenDataset]())
    service.load_all()
    dataset = service.get_dataset("customer_support_bot", "1.0.0")
    fixtures = service.get_fixtures(dataset)

    runner = EvaluationRunner()
    _, results = runner.run(dataset, fixtures)
    return {r.case_id: r for r in results}


def test_seed_dataset_has_six_critical_cases(seed_results):
    dataset_critical_ids = {
        case_id for case_id, result in seed_results.items() if result.case_id in CRITICAL_CASE_IDS
    }
    assert dataset_critical_ids == CRITICAL_CASE_IDS


@pytest.mark.parametrize("case_id", sorted(CRITICAL_CASE_IDS - EXPECTED_CRITICAL_FAILURES))
def test_passing_critical_cases_do_not_flag_critical_failure(seed_results, case_id):
    result = seed_results[case_id]

    assert result.passed is True
    assert result.critical_failure is False


@pytest.mark.parametrize("case_id", sorted(EXPECTED_CRITICAL_FAILURES))
def test_failing_critical_cases_flag_critical_failure(seed_results, case_id):
    result = seed_results[case_id]

    assert result.passed is False
    assert result.critical_failure is True


def test_non_critical_case_failure_never_sets_critical_failure(seed_results):
    non_critical_failures = [
        result
        for case_id, result in seed_results.items()
        if case_id not in CRITICAL_CASE_IDS and not result.passed
    ]

    assert non_critical_failures
    assert all(result.critical_failure is False for result in non_critical_failures)


def test_overall_seed_dataset_pass_fail_counts(seed_results):
    results = list(seed_results.values())
    passed = sum(1 for r in results if r.passed)

    assert len(results) == 22
    assert passed == 15
    assert len(results) - passed == 7
