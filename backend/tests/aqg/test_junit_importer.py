"""M2: JUnit XML importer, tested on real pytest, Vitest and Playwright output.

Broken inputs are built from the real fixtures inside each test, so every
case starts from a file a real tool wrote. See fixtures/junit/README.md.
"""

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aqg.evidence import CheckSource, CheckStatus, EvidenceRun
from aqg.importers import (
    DuplicateIds,
    JUnitInput,
    JUnitInputError,
    import_junit,
    read_junit,
)

FIXTURES = Path(__file__).parent / "fixtures" / "junit"
CREATED = datetime(2026, 11, 23, 9, 0, tzinfo=UTC)


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _write(tmp_path: Path, text: str | bytes, name: str = "report.xml") -> Path:
    path = tmp_path / name
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8")
    return path


def _statuses(report) -> dict[str, int]:
    return dict(Counter(c.status.value for c in report.checks))


def _by_name(report) -> dict:
    return {c.name: c for c in report.checks}


# --- real fixtures: counts must match each tool's own summary ---------------


def test_pytest_fixture_matches_pytest_summary():
    # pytest: "1 failed, 5 passed, 1 skipped, 1 xfailed, 1 error, 3 rerun"
    report = read_junit(JUnitInput(FIXTURES / "pytest.xml"))
    assert report.source is CheckSource.PYTEST
    assert _statuses(report) == {"passed": 5, "failed": 1, "error": 1, "skipped": 2}
    checks = _by_name(report)
    assert checks["test_fails"].status is CheckStatus.FAILED
    assert "assert 'export' == 'exports'" in checks["test_fails"].message
    assert checks["test_errors_in_setup"].status is CheckStatus.ERROR
    assert "database not reachable" in checks["test_errors_in_setup"].message
    assert checks["test_skipped"].message == "not supported on CI"
    assert checks["test_expected_failure"].status is CheckStatus.SKIPPED  # xfail
    assert (
        checks["test_downloads_html"].id == "pytest::sample_suite.TestExport::test_downloads_html"
    )
    assert report.warnings == () and report.blockers == ()


def test_vitest_fixture_matches_vitest_summary():
    # Vitest: "2 failed | 3 passed | 1 skipped | 1 todo (7)"
    report = read_junit(JUnitInput(FIXTURES / "vitest.xml"))
    assert report.source is CheckSource.VITEST
    assert _statuses(report) == {"passed": 3, "failed": 2, "skipped": 2}
    checks = _by_name(report)
    # Vitest reports a thrown error as a failure, not an <error>.
    assert checks["parser > throws while parsing"].status is CheckStatus.FAILED
    assert checks["markdown export > supports footnotes"].status is CheckStatus.SKIPPED  # todo
    assert checks["markdown export > renders headings"].id == (
        "src/sample.spec.ts::src/sample.spec.ts::markdown export > renders headings"
    )


def test_playwright_fixture_matches_playwright_summary():
    # Playwright: "2 failed, 1 flaky, 2 skipped, 2 passed"; one failure is a timeout.
    report = read_junit(JUnitInput(FIXTURES / "playwright.xml"))
    assert report.source is CheckSource.PLAYWRIGHT
    assert _statuses(report) == {"passed": 3, "failed": 1, "error": 1, "skipped": 2}
    checks = _by_name(report)
    assert checks["export › times out"].status is CheckStatus.ERROR
    assert checks["export › times out"].message == "Test timeout of 200ms exceeded."
    assert checks["export › keeps code blocks"].status is CheckStatus.FAILED
    assert checks["converts CLaaT codelab"].status is CheckStatus.SKIPPED  # fixme


def test_durations_are_milliseconds():
    checks = _by_name(read_junit(JUnitInput(FIXTURES / "playwright.xml")))
    assert checks["export › times out"].duration_ms == 404.0
    assert checks["export › exports PDF"].duration_ms is None  # no time= attribute


def test_unicode_names_survive():
    vitest = _by_name(read_junit(JUnitInput(FIXTURES / "vitest.xml")))
    playwright = _by_name(read_junit(JUnitInput(FIXTURES / "playwright.xml")))
    assert vitest["markdown export > handles ünïcode titles ✓"].status is CheckStatus.PASSED
    assert playwright["export › reopens ünïcode lab ✓"].status is CheckStatus.PASSED


def test_suite_label_becomes_first_part_of_id():
    report = read_junit(JUnitInput(FIXTURES / "vitest.xml", suite="unit"))
    assert all(c.id.startswith("unit::src/sample.spec.ts::") for c in report.checks)
    assert {c.suite for c in report.checks} == {"unit"}


def test_ids_are_stable_across_reads():
    first = [c.id for c in read_junit(JUnitInput(FIXTURES / "pytest.xml")).checks]
    second = [c.id for c in read_junit(JUnitInput(FIXTURES / "pytest.xml")).checks]
    assert first == second


# --- retries and flaky tests ------------------------------------------------


def test_pytest_rerun_that_passes_is_flaky():
    report = read_junit(JUnitInput(FIXTURES / "pytest.xml"))
    flaky = _by_name(report)["test_flaky_passes_on_retry"]
    assert flaky.status is CheckStatus.PASSED
    assert flaky.tags == ["flaky"]
    assert [c.name for c in report.checks if c.tags] == ["test_flaky_passes_on_retry"]


def test_pytest_rerun_that_keeps_failing_is_one_failed_check():
    report = read_junit(JUnitInput(FIXTURES / "pytest.xml"))
    assert [c.name for c in report.checks].count("test_fails") == 1
    assert _by_name(report)["test_fails"].tags == []


def test_pytest_teardown_error_is_error_not_passed():
    # pytest writes "failed, then errored in teardown" as two entries with the
    # same id, and tests="3" for 2 tests. The last entry decides.
    report = read_junit(JUnitInput(FIXTURES / "pytest-teardown.xml"))
    assert _statuses(report) == {"error": 2}
    assert "teardown boom" in _by_name(report)["test_fail_and_teardown_error"].message


def test_vitest_retries_stay_one_failed_check():
    report = read_junit(JUnitInput(FIXTURES / "vitest.xml"))
    assert [c.name for c in report.checks].count("markdown export > escapes HTML") == 1
    assert _by_name(report)["markdown export > escapes HTML"].status is CheckStatus.FAILED


@pytest.mark.parametrize(
    ("fixture", "name"),
    [
        ("vitest.xml", "markdown export > passes on retry"),
        ("playwright.xml", "export › passes on retry"),
    ],
)
def test_vitest_and_playwright_junit_hide_flaky_tests(fixture, name):
    # Known tool limitation: their JUnit output only shows the final result.
    # The status is right (passed); the flaky tag can't be set from JUnit alone.
    check = _by_name(read_junit(JUnitInput(FIXTURES / fixture)))[name]
    assert check.status is CheckStatus.PASSED
    assert check.tags == []


def test_retries_are_only_grouped_when_consecutive_in_pytest(tmp_path):
    text = _fixture("pytest.xml").replace(
        '<testcase classname="sample_suite.TestExport" name="test_downloads_html" time="0.000" />',
        '<testcase classname="sample_suite" name="test_passes" time="0.000" />',
    )
    assert text != _fixture("pytest.xml")
    with pytest.raises(JUnitInputError, match="duplicate test ids"):
        read_junit(JUnitInput(_write(tmp_path, text)))


# --- duplicate ids --------------------------------------------------------------


def test_duplicate_ids_are_an_input_error_by_default():
    with pytest.raises(JUnitInputError) as exc:
        read_junit(JUnitInput(FIXTURES / "playwright-two-projects.xml"))
    assert "duplicate test ids" in str(exc.value)
    assert "includeProjectInTestName: true" in str(exc.value)


def test_duplicate_ids_can_be_numbered_with_a_warning():
    report = read_junit(
        JUnitInput(FIXTURES / "playwright-two-projects.xml"), duplicates=DuplicateIds.NUMBER
    )
    ids = [c.id for c in report.checks]
    assert ids == [
        "export.spec.ts::export.spec.ts::export › downloads HTML",
        "export.spec.ts::export.spec.ts::export › downloads HTML#2",
    ]
    assert len(report.warnings) == 1 and "numbered as" in report.warnings[0]


def test_vitest_duplicate_is_never_treated_as_a_retry(tmp_path):
    text = _fixture("vitest.xml")
    case = text[text.index("<testcase") : text.index("</testcase>") + len("</testcase>")]
    # The same test twice in a row: a retry for pytest, but a duplicate for Vitest.
    text = text.replace(case, case + "\n" + case, 1)
    text = text.replace('tests="7"', 'tests="8"')
    path = _write(tmp_path, text)
    with pytest.raises(JUnitInputError, match="duplicate test ids"):
        read_junit(JUnitInput(path))
    numbered = read_junit(JUnitInput(path), duplicates="number")
    assert len(numbered.checks) == 8


def test_duplicate_ids_across_files(tmp_path):
    first = _write(tmp_path, _fixture("vitest.xml"), "a.xml")
    second = _write(tmp_path, _fixture("vitest.xml"), "b.xml")
    with pytest.raises(JUnitInputError, match="Give each input a suite label"):
        import_junit([JUnitInput(first), JUnitInput(second)], project="p", created_at=CREATED)
    labelled = import_junit(
        [JUnitInput(first, suite="a"), JUnitInput(second, suite="b")],
        project="p",
        created_at=CREATED,
    )
    assert len(labelled.run.checks) == 14
    numbered = import_junit(
        [JUnitInput(first), JUnitInput(second)],
        project="p",
        created_at=CREATED,
        duplicates=DuplicateIds.NUMBER,
    )
    assert len(numbered.run.checks) == 14 and len(numbered.warnings) == 7


# --- several files at once ------------------------------------------------------


def test_three_tools_import_into_one_run():
    result = import_junit(
        [
            JUnitInput(FIXTURES / "pytest.xml", suite="backend"),
            JUnitInput(FIXTURES / "vitest.xml", suite="unit"),
            JUnitInput(FIXTURES / "playwright.xml", suite="e2e"),
        ],
        project="steplab",
        version="1.4.0",
        commit="abc1234",
        created_at=CREATED,
    )
    run = result.run
    assert len(run.checks) == 9 + 7 + 7
    assert [i.path for i in run.inputs] == [
        str(FIXTURES / "pytest.xml"),
        str(FIXTURES / "vitest.xml"),
        str(FIXTURES / "playwright.xml"),
    ]
    assert {c.source.value for c in run.checks} == {"pytest", "vitest", "playwright"}
    assert result.flaky == ("backend::sample_suite::test_flaky_passes_on_retry",)
    assert result.warnings == () and result.blockers == ()
    assert EvidenceRun.model_validate_json(run.model_dump_json()) == run


def test_no_inputs_is_an_input_error():
    with pytest.raises(JUnitInputError, match="no JUnit result files"):
        import_junit([], project="p")


def test_blockers_are_collected_from_every_file(tmp_path):
    empty = _write(tmp_path, '<testsuites name="vitest tests" tests="0"></testsuites>', "e.xml")
    result = import_junit(
        [JUnitInput(FIXTURES / "vitest.xml"), JUnitInput(empty)], project="p", created_at=CREATED
    )
    assert len(result.run.checks) == 7
    assert result.blockers == (f"{empty}: no test cases found, so nothing ran",)


# --- incomplete evidence: input error or BLOCK, never PASS ------------------------


def test_empty_report_blocks(tmp_path):
    path = _write(tmp_path, '<?xml version="1.0"?><testsuites name="pytest tests"/>')
    report = read_junit(JUnitInput(path))
    assert report.checks == ()
    assert report.blockers == (f"{path}: no test cases found, so nothing ran",)


def test_min_checks_blocks_when_too_few_tests(tmp_path):
    report = read_junit(JUnitInput(FIXTURES / "vitest.xml", min_checks=8))
    assert report.blockers == (
        f"{FIXTURES / 'vitest.xml'}: 7 tests found, fewer than min_checks 8",
    )
    assert read_junit(JUnitInput(FIXTURES / "vitest.xml", min_checks=7)).blockers == ()


@pytest.mark.parametrize("value", [0, -1, True, 2.5, "3"])
def test_min_checks_must_be_a_positive_whole_number(value):
    with pytest.raises(ValueError, match="min_checks"):
        JUnitInput(FIXTURES / "vitest.xml", min_checks=value)


def test_missing_file_is_an_input_error(tmp_path):
    with pytest.raises(JUnitInputError, match="result file not found"):
        read_junit(JUnitInput(tmp_path / "nope.xml"))


def test_directory_is_an_input_error(tmp_path):
    with pytest.raises(JUnitInputError, match="not a file"):
        read_junit(JUnitInput(tmp_path))


@pytest.mark.parametrize("content", [b"", b"   \n"])
def test_empty_file_is_an_input_error(tmp_path, content):
    with pytest.raises(JUnitInputError, match="empty"):
        read_junit(JUnitInput(_write(tmp_path, content)))


@pytest.mark.parametrize("fixture", ["pytest.xml", "vitest.xml", "playwright.xml"])
@pytest.mark.parametrize("fraction", [0.25, 0.5, 0.9])
def test_report_cut_off_mid_file_is_an_input_error(tmp_path, fixture, fraction):
    data = (FIXTURES / fixture).read_bytes()
    path = _write(tmp_path, data[: int(len(data) * fraction)])
    with pytest.raises(JUnitInputError, match="truncated or not valid XML"):
        read_junit(JUnitInput(path))


def test_report_missing_only_its_closing_tag_is_an_input_error(tmp_path):
    text = _fixture("vitest.xml").rstrip()
    assert text.endswith("</testsuites>")
    with pytest.raises(JUnitInputError, match="truncated or not valid XML"):
        read_junit(JUnitInput(_write(tmp_path, text[: -len("</testsuites>")])))


def test_count_mismatch_is_an_input_error(tmp_path):
    text = _fixture("vitest.xml")
    start = text.rindex("<testcase")
    end = text.rindex("</testcase>") + len("</testcase>")
    with pytest.raises(JUnitInputError, match="declares 7 tests but contains only 6"):
        read_junit(JUnitInput(_write(tmp_path, text[:start] + text[end:])))


def test_more_different_tests_than_declared_is_an_input_error(tmp_path):
    text = _fixture("playwright.xml").replace('tests="7"', 'tests="6"')
    with pytest.raises(JUnitInputError, match="declares 6 tests but contains 7 different"):
        read_junit(JUnitInput(_write(tmp_path, text)))


def test_non_numeric_tests_count_is_an_input_error(tmp_path):
    text = _fixture("vitest.xml").replace('tests="7"', 'tests="seven"', 1)
    with pytest.raises(JUnitInputError, match="not a whole number"):
        read_junit(JUnitInput(_write(tmp_path, text)))


def test_doctype_is_refused(tmp_path):
    bomb = (
        '<?xml version="1.0"?>\n'
        '<!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;">]>\n'
        '<testsuites name="pytest tests"><testsuite name="pytest" tests="1">'
        '<testcase classname="a" name="&lol2;"/></testsuite></testsuites>'
    )
    with pytest.raises(JUnitInputError, match="DOCTYPE"):
        read_junit(JUnitInput(_write(tmp_path, bomb)))


def test_external_doctype_is_refused(tmp_path):
    text = _fixture("vitest.xml").replace(
        '<?xml version="1.0" encoding="UTF-8" ?>',
        '<?xml version="1.0" encoding="UTF-8" ?>\n<!DOCTYPE x SYSTEM "http://example.invalid/x.dtd">',
    )
    with pytest.raises(JUnitInputError, match="DOCTYPE"):
        read_junit(JUnitInput(_write(tmp_path, text)))


def test_utf16_doctype_is_refused(tmp_path):
    text = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE x><testsuites/>'
    with pytest.raises(JUnitInputError, match="DOCTYPE"):
        read_junit(JUnitInput(_write(tmp_path, text.encode("utf-16"))))


def test_oversized_file_is_an_input_error():
    with pytest.raises(JUnitInputError, match="over the 1000 limit"):
        read_junit(JUnitInput(FIXTURES / "vitest.xml"), max_bytes=1000)


def test_wrong_root_element_is_an_input_error(tmp_path):
    with pytest.raises(JUnitInputError, match="root element is <html>"):
        read_junit(JUnitInput(_write(tmp_path, "<html><body/></html>")))


def test_unknown_tool_needs_an_explicit_source(tmp_path):
    text = '<testsuite name="other" tests="1"><testcase classname="c" name="t"/></testsuite>'
    path = _write(tmp_path, text)
    with pytest.raises(JUnitInputError, match="can't tell which tool"):
        read_junit(JUnitInput(path))
    report = read_junit(JUnitInput(path, source=CheckSource.VITEST))
    assert report.source is CheckSource.VITEST
    assert report.checks[0].id == "other::c::t"


def test_llm_is_not_a_junit_source():
    with pytest.raises(ValueError, match="pytest, vitest or playwright"):
        JUnitInput(FIXTURES / "vitest.xml", source=CheckSource.LLM)


@pytest.mark.parametrize("suite", ["", " ", " unit"])
def test_suite_label_must_be_clean(suite):
    with pytest.raises(ValueError, match="suite"):
        JUnitInput(FIXTURES / "vitest.xml", suite=suite)


def test_testcase_without_name_is_an_input_error(tmp_path):
    text = '<testsuites name="vitest tests"><testsuite name="s"><testcase classname="c"/>'
    text += "</testsuite></testsuites>"
    with pytest.raises(JUnitInputError, match="has no name"):
        read_junit(JUnitInput(_write(tmp_path, text)))


@pytest.mark.parametrize("time", ["abc", "-1", "nan", "inf"])
def test_bad_time_is_an_input_error(tmp_path, time):
    text = _fixture("vitest.xml").replace('time="0.003437724"', f'time="{time}"')
    with pytest.raises(JUnitInputError, match="time="):
        read_junit(JUnitInput(_write(tmp_path, text)))


def test_nested_testsuites_are_flattened(tmp_path):
    text = (
        '<testsuites name="vitest tests" tests="3">'
        '<testsuite name="outer" tests="3">'
        '<testcase classname="c" name="a"/>'
        '<testsuite name="inner" tests="2">'
        '<testcase classname="c" name="b"><failure message="no"/></testcase>'
        '<testcase classname="c" name="a"><skipped/></testcase>'
        "</testsuite></testsuite></testsuites>"
    )
    report = read_junit(JUnitInput(_write(tmp_path, text)))
    assert [(c.id, c.status.value) for c in report.checks] == [
        ("outer::c::a", "passed"),
        ("inner::c::b", "failed"),
        ("inner::c::a", "skipped"),
    ]


def test_long_messages_are_shortened(tmp_path):
    text = _fixture("vitest.xml").replace(
        'message="cannot read properties of undefined"', f'message="{"x" * 5000}"'
    )
    check = _by_name(read_junit(JUnitInput(_write(tmp_path, text))))[
        "parser > throws while parsing"
    ]
    assert len(check.message) == 4000 and check.message.endswith("…")


INCOMPLETE = {
    "empty report": '<testsuites name="pytest tests" tests="0"/>',
    "empty file": "",
    "truncated": _fixture("playwright.xml")[:1500],
    "count mismatch": _fixture("vitest.xml").replace('tests="7"', 'tests="9"'),
    "doctype": '<!DOCTYPE x [<!ENTITY a "b">]><testsuites name="pytest tests"/>',
    "not junit": "<report/>",
}


@pytest.mark.parametrize("case", sorted(INCOMPLETE))
def test_incomplete_evidence_never_passes(tmp_path, case):
    """M2 acceptance: every incomplete-evidence case is an input error or BLOCK."""
    path = _write(tmp_path, INCOMPLETE[case])
    try:
        report = read_junit(JUnitInput(path, min_checks=1))
    except JUnitInputError:
        return
    assert report.blockers, f"{case} produced no input error and no blocker"
