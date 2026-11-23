"""M1: validation and JSON round trip for the quality-evidence model."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from aqg.evidence import (
    SCHEMA_VERSION,
    CheckEvidence,
    CheckSource,
    CheckStatus,
    EvidenceInput,
    EvidenceRun,
    InputFormat,
)

CREATED = datetime(2026, 11, 23, 8, 0, tzinfo=UTC)


def _check(check_id: str = "unit::tests.test_a::test_ok", **overrides) -> dict:
    data = {
        "id": check_id,
        "name": "test_ok",
        "suite": "unit",
        "source": "pytest",
        "status": "passed",
    }
    data.update(overrides)
    return data


def _run(checks: list[dict] | None = None, **overrides) -> dict:
    data = {
        "project": "steplab",
        "version": "1.4.0",
        "commit": "0123456789abcdef0123456789abcdef01234567",
        "created_at": CREATED.isoformat(),
        "inputs": [{"format": "junit", "path": "reports/unit.xml"}],
        "checks": checks if checks is not None else [_check()],
    }
    data.update(overrides)
    return data


# --- valid evidence --------------------------------------------------------


def test_minimal_check_defaults():
    check = CheckEvidence.model_validate(_check())
    assert check.status is CheckStatus.PASSED
    assert check.source is CheckSource.PYTEST
    assert check.duration_ms is None
    assert check.message is None
    assert check.metrics == {}
    assert check.tags == []


@pytest.mark.parametrize("status", ["passed", "failed", "skipped", "error"])
def test_every_status_is_accepted(status):
    assert CheckEvidence.model_validate(_check(status=status)).status == status


@pytest.mark.parametrize("source", ["pytest", "vitest", "playwright", "llm"])
def test_every_source_is_accepted(source):
    assert CheckEvidence.model_validate(_check(source=source)).source == source


def test_run_defaults_schema_version():
    run = EvidenceRun.model_validate(_run())
    assert run.schema_version == SCHEMA_VERSION == "1"
    assert run.inputs == [EvidenceInput(format=InputFormat.JUNIT, path="reports/unit.xml")]


def test_empty_run_is_valid_so_policy_can_block_it():
    # Decision 7: an empty report must never pass. The model keeps it so the
    # policy (M4) can return BLOCK, instead of dropping it silently.
    run = EvidenceRun.model_validate(_run(checks=[]))
    assert run.checks == []


def test_models_are_immutable():
    run = EvidenceRun.model_validate(_run())
    with pytest.raises(ValidationError):
        run.project = "other"
    with pytest.raises(ValidationError):
        run.checks[0].status = CheckStatus.FAILED


# --- invalid evidence ------------------------------------------------------


@pytest.mark.parametrize("bad_id", ["", "   ", "\t", " leading", "trailing "])
def test_blank_or_padded_check_id_is_rejected(bad_id):
    with pytest.raises(ValidationError, match="id"):
        CheckEvidence.model_validate(_check(bad_id))


@pytest.mark.parametrize("field", ["name", "suite"])
def test_blank_name_or_suite_is_rejected(field):
    with pytest.raises(ValidationError, match=field):
        CheckEvidence.model_validate(_check(**{field: " "}))


def test_duplicate_check_ids_are_rejected():
    checks = [
        _check("e2e::export::download"),
        _check("unit::a::b"),
        _check("e2e::export::download", status="failed"),
    ]
    with pytest.raises(ValidationError, match="duplicate check ids: e2e::export::download"):
        EvidenceRun.model_validate(_run(checks=checks))


def test_ids_differing_only_in_case_are_distinct():
    run = EvidenceRun.model_validate(_run(checks=[_check("a::b::C"), _check("a::b::c")]))
    assert len(run.checks) == 2


@pytest.mark.parametrize("status", ["flaky", "missing", "PASSED", "pass", "ok", "", None])
def test_unknown_status_is_rejected(status):
    with pytest.raises(ValidationError, match="status"):
        CheckEvidence.model_validate(_check(status=status))


def test_unknown_source_is_rejected():
    with pytest.raises(ValidationError, match="source"):
        CheckEvidence.model_validate(_check(source="jest"))


@pytest.mark.parametrize("missing", ["id", "name", "source", "status"])
def test_required_check_fields(missing):
    data = _check()
    del data[missing]
    with pytest.raises(ValidationError, match=missing):
        CheckEvidence.model_validate(data)


@pytest.mark.parametrize("missing", ["project", "created_at"])
def test_required_run_fields(missing):
    data = _run()
    del data[missing]
    with pytest.raises(ValidationError, match=missing):
        EvidenceRun.model_validate(data)


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError, match="extra"):
        CheckEvidence.model_validate(_check(retries=2))
    with pytest.raises(ValidationError, match="extra"):
        EvidenceRun.model_validate(_run(branch="main"))


@pytest.mark.parametrize("version", ["2", "0", 1, ""])
def test_unknown_schema_version_is_rejected(version):
    with pytest.raises(ValidationError, match="schema_version"):
        EvidenceRun.model_validate(_run(schema_version=version))


def test_naive_created_at_is_rejected():
    with pytest.raises(ValidationError, match="created_at"):
        EvidenceRun.model_validate(_run(created_at="2026-11-23T08:00:00"))


@pytest.mark.parametrize("duration", [-1, float("nan"), float("inf")])
def test_bad_duration_is_rejected(duration):
    with pytest.raises(ValidationError, match="duration_ms"):
        CheckEvidence.model_validate(_check(duration_ms=duration))


@pytest.mark.parametrize("value", [float("nan"), float("inf"), "high"])
def test_bad_metric_value_is_rejected(value):
    with pytest.raises(ValidationError, match="metrics"):
        CheckEvidence.model_validate(_check(metrics={"faithfulness": value}))


def test_blank_tag_is_rejected():
    with pytest.raises(ValidationError, match="tags"):
        CheckEvidence.model_validate(_check(tags=["smoke", " "]))


def test_bad_input_is_rejected():
    with pytest.raises(ValidationError, match="format"):
        EvidenceRun.model_validate(_run(inputs=[{"format": "quality-checker", "path": "x.json"}]))
    with pytest.raises(ValidationError, match="path"):
        EvidenceRun.model_validate(_run(inputs=[{"format": "junit", "path": ""}]))


# --- JSON round trip -------------------------------------------------------


def _full_run() -> EvidenceRun:
    return EvidenceRun.model_validate(
        _run(
            inputs=[
                {"format": "junit", "path": "reports/unit.xml"},
                {"format": "junit", "path": "reports/e2e.xml"},
                {"format": "llm", "path": "run-42"},
            ],
            checks=[
                _check(duration_ms=12.5),
                _check(
                    "unit::tests.test_a::test_bad",
                    name="test_bad",
                    status="failed",
                    message="AssertionError: 1 != 2",
                ),
                _check(
                    "e2e::export.spec.ts::downloads HTML — ünïcode ✓",
                    name="downloads HTML — ünïcode ✓",
                    suite="e2e",
                    source="playwright",
                    status="skipped",
                    message="skipped on CI",
                    tags=["export", "smoke"],
                ),
                _check("vitest::parser::crashes", source="vitest", status="error"),
                _check(
                    "llm::case-7::faithfulness",
                    name="faithfulness",
                    suite=None,
                    source="llm",
                    metrics={"faithfulness": 0.82, "threshold": 0.7},
                ),
            ],
        )
    )


def test_json_round_trip_is_lossless():
    run = _full_run()
    text = run.model_dump_json()
    again = EvidenceRun.model_validate_json(text)
    assert again == run
    assert again.model_dump_json() == text


def test_json_uses_plain_status_strings():
    dumped = _full_run().model_dump(mode="json")
    assert [c["status"] for c in dumped["checks"]] == [
        "passed",
        "failed",
        "skipped",
        "error",
        "passed",
    ]
    assert dumped["created_at"] == "2026-11-23T08:00:00Z"
