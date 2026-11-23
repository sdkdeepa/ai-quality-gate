"""M4: evidence policy and gate decision, one or more tests per rule."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from aqg.evidence import CheckEvidence, EvidenceRun
from aqg.importers import JUnitInput, import_junit
from aqg.policy import (
    Action,
    EvidenceDecision,
    EvidencePolicy,
    GateStatus,
    decide,
    pattern_matcher,
)

FIXTURES = Path(__file__).parent / "fixtures" / "junit"
CREATED = datetime(2026, 11, 23, 10, 0, tzinfo=UTC)
PASS, WARN, BLOCK = GateStatus.PASS, GateStatus.WARN, GateStatus.BLOCK


def _run(*checks: tuple) -> EvidenceRun:
    """Each check is (id, status) or (id, status, tags)."""
    return EvidenceRun(
        project="p",
        created_at=CREATED,
        checks=[
            CheckEvidence(
                id=c[0],
                name=c[0].rsplit("::", 1)[-1],
                source="pytest",
                status=c[1],
                tags=list(c[2]) if len(c) > 2 else [],
            )
            for c in checks
        ],
    )


OK = ("unit::a::ok", "passed")


def _decide(*checks: tuple, **policy) -> EvidenceDecision:
    return decide(_run(*checks), EvidencePolicy(**policy))


# --- rules that can't be configured away ----------------------------------------


def test_empty_run_blocks():
    decision = _decide()
    assert decision.status is BLOCK
    assert decision.blocking == ["no checks were found, so nothing ran"]
    assert decision.pass_rate is None


def test_all_skipped_blocks_even_when_skips_are_ignored():
    decision = _decide(("a::b::c", "skipped"), on_optional_skipped="ignore")
    assert decision.status is BLOCK
    assert "every check was skipped or errored" in decision.blocking[0]


def test_all_errored_blocks_even_when_errors_are_ignored():
    decision = _decide(("a::b::c", "error"), on_optional_error="ignore")
    assert decision.status is BLOCK
    assert "nothing really ran" in decision.blocking[0]


def test_input_blockers_block_and_come_first():
    decision = decide(
        _run(OK, ("a::b::skip", "skipped")),
        EvidencePolicy(),
        input_blockers=["reports/e2e.xml: no test cases found, so nothing ran"],
    )
    assert decision.status is BLOCK
    assert decision.reasons[0] == "reports/e2e.xml: no test cases found, so nothing ran"
    assert decision.warnings == ["1 optional check skipped: a::b::skip"]


# --- all good -----------------------------------------------------------------------


def test_all_passed_is_pass():
    decision = _decide(OK, ("unit::a::ok2", "passed"))
    assert decision.status is PASS
    assert decision.reasons == []
    assert decision.counts.model_dump() == {
        "total": 2,
        "passed": 2,
        "failed": 0,
        "skipped": 0,
        "error": 0,
        "flaky": 0,
    }
    assert decision.pass_rate == 1.0


# --- optional checks ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("action", "expected"), [(None, BLOCK), ("warn", WARN), ("ignore", PASS), ("block", BLOCK)]
)
def test_optional_failed(action, expected):
    policy = {} if action is None else {"on_optional_failed": action}
    decision = _decide(OK, ("unit::a::bad", "failed"), **policy)
    assert decision.status is expected
    if expected is not PASS:
        assert decision.reasons == ["1 optional check failed: unit::a::bad"]


@pytest.mark.parametrize(
    ("action", "expected"), [(None, WARN), ("warn", WARN), ("ignore", PASS), ("block", BLOCK)]
)
def test_optional_skipped(action, expected):
    policy = {} if action is None else {"on_optional_skipped": action}
    assert _decide(OK, ("unit::a::skip", "skipped"), **policy).status is expected


@pytest.mark.parametrize(
    ("action", "expected"), [(None, BLOCK), ("warn", WARN), ("ignore", PASS), ("block", BLOCK)]
)
def test_optional_error(action, expected):
    policy = {} if action is None else {"on_optional_error": action}
    assert _decide(OK, ("unit::a::crash", "error"), **policy).status is expected


def test_error_and_failed_are_reported_separately():
    decision = _decide(OK, ("unit::a::bad", "failed"), ("unit::a::crash", "error"))
    assert decision.blocking == [
        "1 optional check failed: unit::a::bad",
        "1 optional check errored: unit::a::crash",
    ]
    # Failing on_optional_failed doesn't hide errors, and the other way round.
    only_errors = _decide(
        OK, ("unit::a::bad", "failed"), ("unit::a::crash", "error"), on_optional_failed="ignore"
    )
    assert only_errors.blocking == ["1 optional check errored: unit::a::crash"]


# --- required checks ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("action", "expected"), [(None, BLOCK), ("warn", WARN), ("ignore", PASS), ("block", BLOCK)]
)
def test_required_but_missing(action, expected):
    policy = {"required": ["e2e::*export*"]} | ({} if action is None else {"on_missing": action})
    decision = _decide(OK, **policy)
    assert decision.status is expected
    assert decision.missing_required == ["e2e::*export*"]
    if expected is not PASS:
        assert decision.reasons == ["1 required check pattern(s) matched no check: e2e::*export*"]


@pytest.mark.parametrize(
    ("action", "expected"), [(None, BLOCK), ("warn", WARN), ("ignore", PASS), ("block", BLOCK)]
)
def test_required_but_skipped(action, expected):
    policy = {"required": ["e2e::export::*"]} | ({} if action is None else {"on_skipped": action})
    decision = _decide(OK, ("e2e::export::download", "skipped"), **policy)
    assert decision.status is expected
    if expected is not PASS:
        assert decision.reasons == ["1 required check skipped: e2e::export::download"]


def test_required_skipped_blocks_while_optional_skipped_warns():
    decision = _decide(
        OK,
        ("e2e::export::download", "skipped"),
        ("e2e::print::pdf", "skipped"),
        required=["e2e::export::*"],
    )
    assert decision.status is BLOCK
    assert decision.blocking == ["1 required check skipped: e2e::export::download"]
    assert decision.warnings == ["1 optional check skipped: e2e::print::pdf"]


@pytest.mark.parametrize(
    ("action", "expected"), [(None, BLOCK), ("warn", WARN), ("ignore", PASS), ("block", BLOCK)]
)
def test_required_error(action, expected):
    policy = {"required": ["e2e::*"]} | ({} if action is None else {"on_error": action})
    assert _decide(OK, ("e2e::export::download", "error"), **policy).status is expected


def test_required_failed_always_blocks():
    decision = _decide(
        OK,
        ("e2e::export::download", "failed"),
        required=["e2e::*"],
        on_optional_failed="ignore",
        on_error="ignore",
        on_skipped="ignore",
    )
    assert decision.status is BLOCK
    assert decision.blocking == ["1 required check failed: e2e::export::download"]


def test_a_check_matched_by_two_patterns_is_reported_once():
    decision = _decide(OK, ("e2e::export::download", "failed"), required=["e2e::*", "*export*"])
    assert decision.blocking == ["1 required check failed: e2e::export::download"]


def test_an_exact_required_id_matches():
    assert _decide(OK, required=["unit::a::ok"]).status is PASS


# --- patterns -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pattern", "check_id", "matches"),
    [
        ("e2e::*export*", "e2e::export.spec.ts::export › downloads HTML", True),
        ("e2e::*export*", "unit::export.spec.ts::x", False),
        ("e2e::*", "e2e::a::b", True),
        ("unit::a::ok", "unit::a::ok", True),
        ("unit::a::ok", "unit::a::ok2", False),  # whole id, not a prefix
        ("unit::a::o?", "unit::a::ok", True),
        ("pytest::s::test_x[café]", "pytest::s::test_x[café]", True),  # brackets are literal
        ("pytest::s::test_x[café]", "pytest::s::test_xc", False),
        ("*::provider", "rag_bot::case-1::provider", True),
        ("a.b::*", "aXb::c", False),  # '.' is literal
    ],
)
def test_pattern_matching(pattern, check_id, matches):
    assert bool(pattern_matcher(pattern).fullmatch(check_id)) is matches


# --- flaky ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("action", "expected"), [(None, WARN), ("warn", WARN), ("ignore", PASS), ("block", BLOCK)]
)
def test_flaky(action, expected):
    policy = {} if action is None else {"on_flaky": action}
    decision = _decide(OK, ("unit::a::retry", "passed", ["flaky"]), **policy)
    assert decision.status is expected
    assert decision.counts.flaky == 1 and decision.counts.passed == 2
    if expected is not PASS:
        assert decision.reasons == ["1 check passed only after a retry (flaky): unit::a::retry"]


def test_flaky_required_check_counts_as_passed():
    decision = _decide(("e2e::a::b", "passed", ["flaky"]), required=["e2e::*"], on_flaky="ignore")
    assert decision.status is PASS


# --- pass rate -----------------------------------------------------------------------


def _ten(failed: int = 0, error: int = 0, skipped: int = 0) -> list[tuple]:
    checks = [(f"u::a::f{i}", "failed") for i in range(failed)]
    checks += [(f"u::a::e{i}", "error") for i in range(error)]
    checks += [(f"u::a::s{i}", "skipped") for i in range(skipped)]
    checks += [(f"u::a::p{i}", "passed") for i in range(10 - len(checks))]
    return checks


LENIENT = {"on_optional_failed": "ignore", "on_optional_error": "ignore"}


def test_min_pass_rate_blocks_below_the_bar():
    decision = _decide(*_ten(failed=1), min_pass_rate=0.95, **LENIENT)
    assert decision.status is BLOCK
    assert decision.blocking == [
        "pass rate 90.00% is below the required minimum 95.00% (9/10 checks that ran passed)"
    ]
    assert _decide(*_ten(failed=1), min_pass_rate=0.9, **LENIENT).status is PASS


def test_errors_count_against_the_pass_rate():
    decision = _decide(*_ten(error=2), min_pass_rate=0.9, **LENIENT)
    assert decision.pass_rate == 0.8 and decision.status is BLOCK


def test_skipped_checks_are_left_out_of_the_pass_rate():
    decision = _decide(*_ten(skipped=5), min_pass_rate=1.0, on_optional_skipped="ignore")
    assert decision.pass_rate == 1.0 and decision.status is PASS
    assert decision.counts.skipped == 5


def test_no_min_pass_rate_by_default():
    assert _decide(*_ten(failed=9), **LENIENT).status is PASS


# --- WARN and CI ---------------------------------------------------------------------


def test_warn_does_not_fail_ci_by_default():
    decision = _decide(OK, ("u::a::skip", "skipped"))
    assert decision.status is WARN and decision.fails_ci is False


def test_fail_on_warn_fails_ci_but_keeps_warn():
    decision = _decide(OK, ("u::a::skip", "skipped"), fail_on_warn=True)
    assert decision.status is WARN and decision.fails_ci is True


@pytest.mark.parametrize("fail_on_warn", [False, True])
def test_block_always_fails_ci_and_pass_never_does(fail_on_warn):
    assert _decide(fail_on_warn=fail_on_warn).fails_ci is True
    assert _decide(OK, fail_on_warn=fail_on_warn).fails_ci is False


def test_blocking_reasons_come_before_warnings():
    decision = _decide(OK, ("u::a::skip", "skipped"), ("u::a::bad", "failed"))
    assert decision.reasons == [
        "1 optional check failed: u::a::bad",
        "1 optional check skipped: u::a::skip",
    ]


def test_long_lists_of_ids_are_shortened():
    checks = [(f"u::a::bad{i}", "failed") for i in range(8)]
    decision = _decide(OK, *checks)
    assert decision.blocking == [
        "8 optional checks failed: u::a::bad0, u::a::bad1, u::a::bad2, u::a::bad3, "
        "u::a::bad4 (+3 more)"
    ]


def test_decision_round_trips_as_json():
    decision = _decide(OK, ("u::a::skip", "skipped"), ("u::a::bad", "failed"))
    assert EvidenceDecision.model_validate_json(decision.model_dump_json()) == decision


# --- policy validation ----------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        {"on_missing": "fail"},
        {"on_flaky": "pass"},
        {"min_pass_rate": 1.5},
        {"min_pass_rate": -0.1},
        {"required": [""]},
        {"required": [" padded"]},
        {"unknown_setting": True},
    ],
)
def test_bad_policies_are_rejected(bad):
    with pytest.raises(ValidationError):
        EvidencePolicy(**bad)


def test_policy_defaults_match_the_plan():
    policy = EvidencePolicy()
    assert (policy.on_missing, policy.on_skipped, policy.on_error) == (
        Action.BLOCK,
        Action.BLOCK,
        Action.BLOCK,
    )
    assert policy.on_optional_skipped is Action.WARN
    assert policy.on_optional_failed is Action.BLOCK
    assert policy.on_optional_error is Action.BLOCK
    assert policy.on_flaky is Action.WARN
    assert policy.min_pass_rate is None
    assert policy.fail_on_warn is False


# --- end to end with the M2 importer ---------------------------------------------------


def test_real_junit_reports_through_the_policy():
    imported = import_junit(
        [
            JUnitInput(FIXTURES / "pytest.xml", suite="backend"),
            JUnitInput(FIXTURES / "vitest.xml", suite="unit"),
            JUnitInput(FIXTURES / "playwright.xml", suite="e2e"),
        ],
        project="steplab",
        created_at=CREATED,
    )
    decision = decide(
        imported.run,
        EvidencePolicy(required=["e2e::*export*"]),
        input_blockers=imported.blockers,
    )
    assert decision.status is BLOCK
    assert decision.counts.model_dump() == {
        "total": 23,
        "passed": 11,
        "failed": 4,
        "skipped": 6,
        "error": 2,
        "flaky": 1,
    }
    assert any(r.startswith("1 required check failed: e2e::") for r in decision.blocking)
    assert any(
        "required check errored: e2e::export.spec.ts::export › times out" in r
        for r in decision.blocking
    )
    assert any(r.startswith("1 check passed only after a retry (flaky)") for r in decision.warnings)
