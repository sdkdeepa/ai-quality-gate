"""M3: the LLM adapter turns existing evaluation runs into evidence, read only.

The core (`aqg`) never imports `app`; these tests do, so they can feed the
adapter the server's real objects and compare it with the server's own
`_metric_status()` classification.
"""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import get_settings
from app.domain.evaluation_case import EvaluationCase
from app.domain.golden_dataset import GoldenDataset
from app.domain.metric_result import MetricResult
from app.evaluation.ragas.client import RagasEvaluatorError, RagasScore
from app.evaluation.ragas.evaluator import RagasFaithfulnessEvaluator
from app.evaluation.runner import EvaluationRunner
from app.evaluation.types import FixtureResponse
from app.main import create_app
from app.policy.engine import _metric_status
from app.providers.deterministic import DeterministicProvider
from app.providers.types import ProviderError, ProviderErrorType, ProviderResponse
from app.repositories.in_memory import InMemoryRepository
from app.services.dataset_service import DatasetService
from aqg.adapters import PROVIDER_CHECK_NAME, evidence_from_llm_run, metric_status
from aqg.evidence import CheckSource, CheckStatus, EvidenceRun, InputFormat

DATASET_DIR = Path(__file__).resolve().parents[2] / "datasets"
DATASET = "customer_support_bot"
VERSIONS = ["1.0.0", "1.1.0"]

# The existing classification, mapped to the explicit evidence statuses.
EXPECTED = {
    ("infrastructure_error", True): CheckStatus.ERROR,
    ("infrastructure_error", False): CheckStatus.ERROR,
    ("skipped", True): CheckStatus.SKIPPED,
    ("skipped", False): CheckStatus.SKIPPED,
    ("scored", True): CheckStatus.PASSED,
    ("scored", False): CheckStatus.FAILED,
}


def _existing_status(metric: MetricResult) -> CheckStatus:
    return EXPECTED[(_metric_status(metric), metric.passed)]


def _m0_run(version: str):
    service = DatasetService(DATASET_DIR, InMemoryRepository())
    service.load_all()
    dataset = service.get_dataset(DATASET, version)
    return EvaluationRunner().run(dataset, service.get_fixtures(dataset))


# --- M0 fixtures (acceptance) --------------------------------------------------


@pytest.mark.parametrize("version", VERSIONS)
def test_every_m0_metric_status_agrees_with_metric_status(version):
    run, cases = _m0_run(version)
    evidence = evidence_from_llm_run(run, cases)
    by_id = {c.id: c for c in evidence.checks}

    metric_count = 0
    for case in cases:
        for metric in case.metric_results:
            metric_count += 1
            check = by_id[f"{DATASET}::{case.case_id}::{metric.metric_name}"]
            assert check.status is _existing_status(metric), check.id
            assert check.metrics == {"score": metric.score, "threshold": metric.threshold}
            assert check.tags[0] == metric.framework
    assert len(evidence.checks) == metric_count > 0


@pytest.mark.parametrize("version", VERSIONS)
def test_m0_run_details_carry_over(version):
    run, cases = _m0_run(version)
    evidence = evidence_from_llm_run(run, cases, commit="abc1234")
    assert evidence.project == DATASET
    assert evidence.version == version
    assert evidence.commit == "abc1234"
    assert evidence.created_at == run.started_at
    assert [(i.format, i.path) for i in evidence.inputs] == [(InputFormat.LLM, run.id)]
    assert {c.source for c in evidence.checks} == {CheckSource.LLM}
    assert {c.suite for c in evidence.checks} == {DATASET}
    assert evidence_from_llm_run(run, cases, project="support-bot").project == "support-bot"


@pytest.mark.parametrize("version", VERSIONS)
def test_m0_case_outcome_is_preserved(version):
    run, cases = _m0_run(version)
    checks = evidence_from_llm_run(run, cases).checks
    for case in cases:
        own = [c for c in checks if c.id.startswith(f"{DATASET}::{case.case_id}::")]
        all_passed = all(c.status is CheckStatus.PASSED for c in own)
        assert all_passed == case.passed, case.case_id
        assert all(("critical_failure" in c.tags) == case.critical_failure for c in own)


def test_m0_critical_failures_are_tagged():
    run, cases = _m0_run("1.0.0")
    checks = evidence_from_llm_run(run, cases).checks
    tagged = sorted({c.id.split("::")[1] for c in checks if "critical_failure" in c.tags})
    assert tagged == sorted(c.case_id for c in cases if c.critical_failure)
    assert tagged  # the 1.0.0 fixtures do contain failed critical cases


def test_ids_are_stable_across_dataset_versions():
    old = {c.id for c in evidence_from_llm_run(*_m0_run("1.0.0")).checks}
    new = {c.id for c in evidence_from_llm_run(*_m0_run("1.1.0")).checks}
    assert old & new  # the same case and metric keeps its id in both versions
    assert all(i.startswith(f"{DATASET}::") for i in old | new)


@pytest.mark.parametrize("version", VERSIONS)
def test_evidence_round_trips_as_json(version):
    evidence = evidence_from_llm_run(*_m0_run(version))
    assert EvidenceRun.model_validate_json(evidence.model_dump_json()) == evidence


@pytest.mark.parametrize("version", VERSIONS)
def test_adapter_is_read_only(version):
    run, cases = _m0_run(version)
    before = (run.model_dump(), [c.model_dump() for c in cases])
    evidence_from_llm_run(run, cases)
    assert (run.model_dump(), [c.model_dump() for c in cases]) == before


def test_json_from_the_api_gives_the_same_evidence(monkeypatch):
    """The adapter reads by field name, so the API's JSON works as well as objects."""
    # A fresh app with default settings, as in the M0 compat tests.
    for name in (
        "AQG_POLICY_DB_PATH",
        "AQG_RAGAS_ENABLED",
        "AQG_DEEPEVAL_ENABLED",
        "AQG_OPENAI_EVALS_ENABLED",
        "AQG_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    try:
        client = TestClient(create_app())
        response = client.post(
            "/api/v1/evaluations/runs", json={"dataset_name": DATASET, "dataset_version": "1.0.0"}
        )
        assert response.status_code == 200
        detail = client.get(f"/api/v1/evaluations/runs/{response.json()['run']['id']}").json()
    finally:
        get_settings.cache_clear()

    from_json = evidence_from_llm_run(detail["run"], detail["case_results"])
    from_objects = evidence_from_llm_run(*_m0_run("1.0.0"))
    assert [(c.id, c.status, c.tags) for c in from_json.checks] == [
        (c.id, c.status, c.tags) for c in from_objects.checks
    ]
    assert from_json.inputs[0].path == detail["run"]["id"]


# --- skipped, error and unreachable cases, from the real evaluators and runner ---


class _CrashingEvaluator:
    name = "crashing_eval"
    framework = "test"

    def applies_to(self, case: EvaluationCase) -> bool:
        return case.id == "evaluator-crash"

    def evaluate(self, evaluation_input):
        raise RuntimeError("a genuine bug in this evaluator")


class _PartlyDownProvider:
    """Deterministic, except the system under test is unreachable for one case."""

    def __init__(self, fixtures: dict[str, FixtureResponse]) -> None:
        self._inner = DeterministicProvider(fixtures, model="fixture-v1", name="deterministic")
        self.name = self._inner.name
        self.model = self._inner.model

    def generate(self, request):
        if request.case_id == "unreachable":
            return ProviderResponse(
                provider=self.name,
                model=self.model,
                latency_ms=0.0,
                error=ProviderError(
                    error_type=ProviderErrorType.UNAVAILABLE, message="connection refused"
                ),
            )
        return self._inner.generate(request)


def _judge(user_input: str, response: str, retrieved_contexts: list[str]) -> RagasScore:
    if response == "JUDGE OUTAGE":
        raise RagasEvaluatorError("judge timed out", error_type=ProviderErrorType.TIMEOUT)
    return RagasScore(value=0.4 if "made up" in response else 0.9)


def _mixed_run():
    def case(case_id: str, critical: bool = False) -> EvaluationCase:
        return EvaluationCase(
            id=case_id, name=case_id, category="rag", query="warranty?", critical=critical
        )

    def fixture(response: str, context: list[str]) -> FixtureResponse:
        return FixtureResponse(
            response=response,
            retrieved_context=context,
            latency_ms=1.0,
            input_tokens=1,
            output_tokens=1,
            estimated_cost=0.0,
        )

    ctx = ["Electronics carry a 1-year warranty."]
    cases = [
        case("grounded"),
        case("ungrounded", critical=True),
        case("no-context"),
        case("judge-down"),
        case("evaluator-crash"),
        case("unreachable", critical=True),
    ]
    fixtures = {
        "grounded": fixture("1-year warranty.", ctx),
        "ungrounded": fixture("A made up 5-year warranty.", ctx),
        "no-context": fixture("1-year warranty.", []),
        "judge-down": fixture("JUDGE OUTAGE", ctx),
        "evaluator-crash": fixture("1-year warranty.", ctx),
        "unreachable": fixture("unused", ctx),
    }
    client = MagicMock()
    client.score_faithfulness.side_effect = _judge
    runner = EvaluationRunner(
        evaluators=[RagasFaithfulnessEvaluator(client=client, threshold=0.8), _CrashingEvaluator()]
    )
    dataset = GoldenDataset(
        name="rag_bot",
        version="2.0.0",
        created_at=datetime.now(UTC),
        description="mixed outcomes",
        cases=cases,
    )
    return runner.run_with_provider(dataset, _PartlyDownProvider(fixtures))


def test_every_mixed_metric_status_agrees_with_metric_status():
    run, cases = _mixed_run()
    by_id = {c.id: c for c in evidence_from_llm_run(run, cases).checks}
    seen = set()
    for case in cases:
        for metric in case.metric_results:
            check = by_id[f"rag_bot::{case.case_id}::{metric.metric_name}"]
            assert check.status is _existing_status(metric), check.id
            seen.add(check.status)
    assert seen == {CheckStatus.PASSED, CheckStatus.FAILED, CheckStatus.SKIPPED, CheckStatus.ERROR}


def test_mixed_run_statuses():
    statuses = {c.id: c.status for c in evidence_from_llm_run(*_mixed_run()).checks}
    assert statuses == {
        "rag_bot::grounded::ragas_faithfulness": CheckStatus.PASSED,
        "rag_bot::ungrounded::ragas_faithfulness": CheckStatus.FAILED,
        "rag_bot::no-context::ragas_faithfulness": CheckStatus.SKIPPED,
        "rag_bot::judge-down::ragas_faithfulness": CheckStatus.ERROR,
        "rag_bot::evaluator-crash::ragas_faithfulness": CheckStatus.PASSED,
        "rag_bot::evaluator-crash::crashing_eval": CheckStatus.ERROR,
        "rag_bot::unreachable::provider": CheckStatus.ERROR,
    }


def test_skipped_metric_is_never_counted_as_passed():
    run, cases = _mixed_run()
    metric = next(c for c in cases if c.case_id == "no-context").metric_results[0]
    assert metric.passed is True  # the server marks "not applicable" as passed=True
    assert metric_status(metric) is CheckStatus.SKIPPED


def test_unreachable_case_becomes_an_error_check_instead_of_vanishing():
    run, cases = _mixed_run()
    unreachable = next(c for c in cases if c.case_id == "unreachable")
    assert unreachable.metric_results == [] and unreachable.error is not None

    check = next(c for c in evidence_from_llm_run(run, cases).checks if c.name == "provider")
    assert check.id == f"rag_bot::unreachable::{PROVIDER_CHECK_NAME}"
    assert check.status is CheckStatus.ERROR
    assert check.message == "unavailable: connection refused"
    assert check.tags == ["provider", "critical_failure"]
    assert check.metrics == {}


def test_error_messages_and_tags_are_kept():
    checks = {c.id: c for c in evidence_from_llm_run(*_mixed_run()).checks}
    judge = checks["rag_bot::judge-down::ragas_faithfulness"]
    assert "infrastructure failure (timeout)" in judge.message
    assert judge.tags == ["ragas"]
    crash = checks["rag_bot::evaluator-crash::crashing_eval"]
    assert "a genuine bug in this evaluator" in crash.message
    assert checks["rag_bot::ungrounded::ragas_faithfulness"].tags == ["ragas", "critical_failure"]
    assert checks["rag_bot::grounded::ragas_faithfulness"].message is None


# --- bad input ---------------------------------------------------------------------


def _metric(**overrides) -> dict:
    data = {
        "metric_name": "exact_match",
        "score": 1.0,
        "threshold": 1.0,
        "passed": True,
        "framework": "deterministic",
        "metadata": {},
    }
    return data | overrides


def _run(**overrides) -> dict:
    data = {
        "id": "run-1",
        "dataset_name": "ds",
        "dataset_version": "1.0.0",
        "started_at": "2026-11-23T09:00:00+00:00",
    }
    return data | overrides


def test_duplicate_metric_on_one_case_is_rejected():
    case = {"case_id": "c1", "metric_results": [_metric(), _metric()]}
    with pytest.raises(ValidationError, match="duplicate check ids: ds::c1::exact_match"):
        evidence_from_llm_run(_run(), [case])


@pytest.mark.parametrize("field", ["id", "dataset_name", "dataset_version"])
def test_missing_run_fields_are_rejected(field):
    with pytest.raises(ValueError, match=field):
        evidence_from_llm_run(_run(**{field: " "}), [])


def test_missing_passed_is_rejected():
    case = {"case_id": "c1", "metric_results": [_metric(passed=None)]}
    with pytest.raises(ValueError, match="boolean 'passed'"):
        evidence_from_llm_run(_run(), [case])


def test_naive_started_at_is_read_as_utc():
    evidence = evidence_from_llm_run(_run(started_at="2026-11-23T09:00:00"), [])
    assert evidence.created_at == datetime(2026, 11, 23, 9, 0, tzinfo=UTC)


def test_run_with_no_cases_has_no_checks():
    # Valid evidence; the M4 policy turns zero checks into BLOCK.
    assert evidence_from_llm_run(_run(), []).checks == []
