"""M5: approved baselines and regression reports."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aqg.baseline import (
    Baseline,
    BaselineError,
    RegressionPolicy,
    Rename,
    apply_regressions,
    approve_baseline,
    baseline_json,
    compare_to_baseline,
    load_baseline,
    write_baseline,
)
from aqg.evidence import CheckEvidence, EvidenceRun
from aqg.importers import JUnitInput, import_junit
from aqg.policy import EvidencePolicy, GateStatus, decide

FIXTURES = Path(__file__).parent / "fixtures" / "junit"
CREATED = datetime(2026, 11, 23, 10, 0, tzinfo=UTC)
APPROVED = datetime(2026, 11, 23, 11, 0, tzinfo=UTC)
LENIENT = EvidencePolicy(
    on_optional_failed="ignore",
    on_optional_error="ignore",
    on_optional_skipped="ignore",
    on_flaky="ignore",
)


def _run(*checks: tuple, project: str = "steplab") -> EvidenceRun:
    """Each check is (id, status) or (id, status, tags)."""
    return EvidenceRun(
        project=project,
        version="1.4.0",
        commit="abc1234",
        created_at=CREATED,
        checks=[
            CheckEvidence(
                id=c[0],
                name=c[0].rsplit("::", 1)[-1],
                source="playwright",
                status=c[1],
                tags=list(c[2]) if len(c) > 2 else [],
            )
            for c in checks
        ],
    )


def _approve(run: EvidenceRun, policy: EvidencePolicy = LENIENT, **kwargs) -> Baseline:
    return approve_baseline(
        run,
        decide(run, policy),
        approved_by="deepa",
        report="quality/report.json",
        approved_at=APPROVED,
        **kwargs,
    )


BASE = (
    ("e2e::export.spec.ts::downloads HTML", "passed"),
    ("e2e::export.spec.ts::keeps code blocks", "passed"),
    ("e2e::upload.spec.ts::reopens lab", "passed"),
    ("e2e::upload.spec.ts::rejects bad md", "failed"),
    ("e2e::claat.spec.ts::converts codelab", "passed"),
    ("e2e::claat.spec.ts::keeps images", "passed"),
    ("unit::parser::handles tables", "passed"),
    ("unit::parser::old name", "passed"),
    ("unit::legacy::a", "passed"),
    ("unit::legacy::b", "passed"),
    ("unit::misc::was skipped", "skipped"),
)


def _base(**kwargs) -> Baseline:
    return _approve(_run(*BASE), **kwargs)


# --- approving ---------------------------------------------------------------------


def test_pass_run_is_approved_with_everything_the_plan_lists():
    baseline = _base()
    assert baseline.project == "steplab"
    assert baseline.version == "1.4.0"
    assert baseline.commit == "abc1234"
    assert baseline.report == "quality/report.json"
    assert baseline.approved_by == "deepa"
    assert baseline.approved_at == APPROVED
    assert baseline.decision is GateStatus.PASS
    assert baseline.checks["e2e::upload.spec.ts::rejects bad md"] == "failed"
    assert baseline.counts.total == 11 and baseline.counts.failed == 1


def test_block_run_is_refused_even_with_allow_warn():
    run = _run(*BASE)
    with pytest.raises(BaselineError, match="BLOCK run can't be approved"):
        _approve(run, EvidencePolicy(), allow_warn=True)


def test_warn_run_needs_allow_warn():
    run = _run(("e2e::a::b", "passed"), ("e2e::a::c", "skipped"))
    with pytest.raises(BaselineError, match="allow_warn"):
        _approve(run, EvidencePolicy())
    baseline = _approve(run, EvidencePolicy(), allow_warn=True)
    assert baseline.decision is GateStatus.WARN


@pytest.mark.parametrize("approved_by", ["", " ", "deepa "])
def test_approver_must_be_named(approved_by):
    run = _run(("e2e::a::b", "passed"))
    with pytest.raises(BaselineError, match="approved_by"):
        approve_baseline(
            run, decide(run, LENIENT), approved_by=approved_by, report="quality/report.json"
        )


def test_flaky_checks_are_recorded():
    baseline = _approve(_run(("e2e::a::b", "passed", ["flaky"]), ("e2e::a::c", "passed")))
    assert baseline.flaky == ["e2e::a::b"]
    assert baseline.counts.flaky == 1


# --- saving and loading -------------------------------------------------------------


def test_write_and_load_round_trip(tmp_path):
    path = tmp_path / "quality" / "baseline.json"
    write_baseline(path, _base())
    assert load_baseline(path) == _base()


def test_file_is_stable_for_review():
    text = baseline_json(_base())
    assert text.endswith("}\n")
    data = json.loads(text)
    assert list(data) == sorted(data)
    assert list(data["checks"]) == sorted(data["checks"])
    assert baseline_json(_base()) == text


def test_missing_baseline_is_a_clear_error(tmp_path):
    with pytest.raises(BaselineError, match="baseline file not found.*aqg baseline approve"):
        load_baseline(tmp_path / "baseline.json")


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("", "empty"),
        ("{not json", "not a valid baseline file"),
        ('{"schema_version": "1"}', "not a valid baseline file"),
        ("[]", "not a valid baseline file"),
    ],
)
def test_corrupt_baseline_is_a_clear_error(tmp_path, content, message):
    path = tmp_path / "baseline.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(BaselineError, match=message):
        load_baseline(path)


def _edited(tmp_path, change) -> Path:
    data = json.loads(baseline_json(_base()))
    change(data)
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d["checks"].pop("unit::legacy::a"), "don't match the checks"),
        (lambda d: d["checks"].update({"unit::legacy::a": "failed"}), "don't match the checks"),
        (lambda d: d.update({"schema_version": "2"}), "schema_version"),
        (lambda d: d.update({"decision": "block"}), "decision"),
        (lambda d: d.update({"checks": {}, "counts": {}}), "at least one check"),
        (lambda d: d.update({"extra": 1}), "extra"),
        (lambda d: d["checks"].update({"unit::legacy::a": "flaky"}), "checks"),
        (lambda d: d.update({"approved_at": "2026-11-23T11:00:00"}), "approved_at"),
    ],
)
def test_hand_edited_or_incomplete_baseline_is_rejected(tmp_path, change, message):
    with pytest.raises(BaselineError, match=message):
        load_baseline(_edited(tmp_path, change))


def test_flaky_id_must_be_a_passed_check(tmp_path):
    def change(d):
        d["flaky"] = ["e2e::upload.spec.ts::rejects bad md"]
        d["counts"]["flaky"] = 1

    with pytest.raises(BaselineError, match="flaky ids must be passed checks"):
        load_baseline(_edited(tmp_path, change))


# --- comparing -----------------------------------------------------------------------


def test_run_compared_with_its_own_baseline_shows_no_changes():
    """M5 acceptance, on a real pytest report (with a failure, an error, skips
    and a flaky test)."""
    imported = import_junit(
        [JUnitInput(FIXTURES / "pytest.xml")], project="gate", created_at=CREATED
    )
    baseline = _approve(imported.run)
    report = compare_to_baseline(imported.run, baseline, required=["pytest::*"])
    assert report.has_changes is False
    assert report == type(report)()


def test_every_regression_type_is_reported_under_its_own_heading():
    current = _run(
        ("e2e::export.spec.ts::downloads HTML", "failed"),  # new failure
        ("e2e::export.spec.ts::keeps code blocks", "error"),  # new failure (error)
        ("e2e::upload.spec.ts::reopens lab", "skipped"),  # skipped required
        ("e2e::upload.spec.ts::rejects bad md", "passed"),  # recovered
        # e2e::claat.spec.ts::converts codelab is gone: required, removed
        ("e2e::claat.spec.ts::keeps images", "passed"),
        ("unit::parser::handles tables", "passed"),
        ("unit::parser::new name", "passed"),  # possible rename of "old name"
        # unit::legacy::a and ::b are gone: optional, removed, two of them so no rename guess
        ("unit::legacy::c", "passed"),  # added
        ("unit::legacy::d", "failed"),  # new failing
        ("unit::misc::was skipped", "skipped"),  # skipped before and now: no change
        ("unit::misc::brand new", "passed"),  # added
    )
    report = compare_to_baseline(current, _base(), required=["e2e::*"])
    assert report.new_failures == [
        "e2e::export.spec.ts::downloads HTML",
        "e2e::export.spec.ts::keeps code blocks",
    ]
    assert report.new_failing == ["unit::legacy::d"]
    assert report.removed == [
        "e2e::claat.spec.ts::converts codelab",
        "unit::legacy::a",
        "unit::legacy::b",
        "unit::parser::old name",
    ]
    assert report.removed_required == ["e2e::claat.spec.ts::converts codelab"]
    assert report.skipped_required == ["e2e::upload.spec.ts::reopens lab"]
    assert report.renamed == []
    assert report.possible_renames == [
        Rename(old="unit::parser::old name", new="unit::parser::new name")
    ]
    assert report.recovered == ["e2e::upload.spec.ts::rejects bad md"]
    assert report.added == ["unit::legacy::c", "unit::misc::brand new", "unit::parser::new name"]


def test_confirmed_rename_is_compared_as_one_test():
    current = _run(
        *[c for c in BASE if c[0] != "unit::parser::old name"]
        + [("unit::parser::new name", "failed")]
    )
    report = compare_to_baseline(
        current, _base(), renames={"unit::parser::old name": "unit::parser::new name"}
    )
    assert report.renamed == [Rename(old="unit::parser::old name", new="unit::parser::new name")]
    assert report.new_failures == ["unit::parser::new name"]  # passed before, under its old id
    assert report.removed == [] and report.added == [] and report.possible_renames == []


def test_confirmed_rename_with_the_same_status_is_only_listed_as_renamed():
    current = _run(
        *[c for c in BASE if c[0] != "unit::parser::old name"]
        + [("unit::parser::new name", "passed")]
    )
    report = compare_to_baseline(
        current, _base(), renames={"unit::parser::old name": "unit::parser::new name"}
    )
    assert report.renamed and not report.new_failures and not report.removed


def test_confirmed_rename_whose_new_id_is_absent_still_reports_removed():
    current = _run(*[c for c in BASE if c[0] != "unit::parser::old name"])
    report = compare_to_baseline(
        current, _base(), renames={"unit::parser::old name": "unit::parser::new name"}
    )
    assert report.renamed == []
    assert report.removed == ["unit::parser::old name"]


def test_possible_rename_needs_the_same_suite_and_file():
    current = _run(
        *[c for c in BASE if c[0] != "unit::parser::old name"]
        + [("unit::other::new name", "passed")]
    )
    report = compare_to_baseline(current, _base())
    assert report.possible_renames == []
    assert "unit::parser::old name" in report.removed


def test_required_skipped_counts_only_if_it_ran_in_the_baseline():
    current = _run(*BASE)
    report = compare_to_baseline(current, _base(), required=["unit::misc::*"])
    assert report.skipped_required == []  # it was already skipped in the baseline


def test_renamed_required_check_now_skipped_is_reported():
    current = _run(
        *[c for c in BASE if c[0] != "e2e::export.spec.ts::downloads HTML"]
        + [("e2e::export.spec.ts::downloads the HTML", "skipped")]
    )
    report = compare_to_baseline(
        current,
        _base(),
        required=["e2e::export.spec.ts::downloads HTML"],
        renames={"e2e::export.spec.ts::downloads HTML": "e2e::export.spec.ts::downloads the HTML"},
    )
    assert report.skipped_required == ["e2e::export.spec.ts::downloads the HTML"]


@pytest.mark.parametrize(
    ("renames", "message"),
    [
        ({"unit::nope::x": "unit::nope::y"}, "is not in the baseline"),
        ({"unit::legacy::a": "unit::legacy::b"}, "already in the baseline"),
        (
            {"unit::legacy::a": "unit::legacy::z", "unit::legacy::b": "unit::legacy::z"},
            "same new id",
        ),
    ],
)
def test_bad_renames_are_errors(renames, message):
    current = _run(*[c for c in BASE if not c[0].startswith("unit::legacy::")])
    with pytest.raises(BaselineError, match=message):
        compare_to_baseline(current, _base(), renames=renames)


def test_rename_of_an_id_that_still_exists_is_an_error():
    with pytest.raises(BaselineError, match="still exists in this run"):
        compare_to_baseline(_run(*BASE), _base(), renames={"unit::legacy::a": "unit::legacy::z"})


def test_baseline_for_another_project_is_an_error():
    with pytest.raises(BaselineError, match="is for project 'steplab', not 'other'"):
        compare_to_baseline(_run(*BASE, project="other"), _base())


# --- what blocks --------------------------------------------------------------------


def _regressed():
    current = _run(*[c for c in BASE if c[0] != "unit::legacy::a"])
    return current, compare_to_baseline(current, _base(), required=["e2e::*"])


def test_policy_defaults_match_the_plan():
    policy = RegressionPolicy()
    assert policy.on_new_failure == "block"
    assert policy.on_new_failing == "block"
    assert policy.on_skipped_required == "block"
    assert policy.on_removed_required == "block"
    assert policy.on_removed == "warn"


@pytest.mark.parametrize(
    ("current", "expected", "reason"),
    [
        (
            [("e2e::export.spec.ts::downloads HTML", "failed")],
            GateStatus.BLOCK,
            "1 check(s) newly failing since the baseline: e2e::export.spec.ts::downloads HTML",
        ),
        (
            [("unit::misc::new", "error")],
            GateStatus.BLOCK,
            "1 new check(s) failing since the baseline: unit::misc::new",
        ),
        (
            [("e2e::upload.spec.ts::reopens lab", "skipped")],
            GateStatus.BLOCK,
            "1 required check(s) now skipped since the baseline: e2e::upload.spec.ts::reopens lab",
        ),
        (
            [("DROP", "e2e::claat.spec.ts::converts codelab")],
            GateStatus.BLOCK,
            "1 required check(s) removed since the baseline: e2e::claat.spec.ts::converts codelab",
        ),
        (
            [("DROP", "unit::legacy::a")],
            GateStatus.WARN,
            "1 check(s) removed since the baseline: unit::legacy::a",
        ),
    ],
)
def test_each_regression_type_and_its_default_action(current, expected, reason):
    checks = dict(BASE)
    for check_id, status in current:
        if check_id == "DROP":
            checks.pop(status)
        else:
            checks[check_id] = status
    run = _run(*checks.items())
    report = compare_to_baseline(run, _base(), required=["e2e::*"])
    decision = apply_regressions(decide(run, LENIENT), report, RegressionPolicy())
    assert decision.status is expected
    assert reason in decision.reasons


def test_possible_rename_warns():
    run = _run(
        *[c for c in BASE if c[0] != "unit::parser::old name"]
        + [("unit::parser::new name", "passed")]
    )
    decision = apply_regressions(
        decide(run, LENIENT), compare_to_baseline(run, _base()), RegressionPolicy()
    )
    assert decision.status is GateStatus.WARN
    assert decision.warnings[-1].startswith("1 possible rename(s); confirm in renames:")


def test_regression_reasons_are_added_after_the_policy_reasons():
    run, report = _regressed()
    first = decide(run, EvidencePolicy())  # blocks on the optional failed check
    decision = apply_regressions(first, report, RegressionPolicy())
    assert decision.blocking == first.blocking
    assert decision.warnings == [
        *first.warnings,
        "1 check(s) removed since the baseline: unit::legacy::a",
    ]


def test_ignored_regressions_leave_the_decision_unchanged():
    run, report = _regressed()
    first = decide(run, LENIENT)
    decision = apply_regressions(first, report, RegressionPolicy(on_removed="ignore"))
    assert decision == first and decision.status is GateStatus.PASS


def test_recovered_and_added_never_block_or_warn():
    run = _run(
        *[(i, "passed") for i, _ in BASE if i != "unit::misc::was skipped"]
        + [("unit::misc::was skipped", "skipped"), ("unit::misc::brand new", "passed")]
    )
    report = compare_to_baseline(run, _base())
    assert report.recovered and report.added
    decision = apply_regressions(decide(run, LENIENT), report, RegressionPolicy())
    assert decision.status is GateStatus.PASS
