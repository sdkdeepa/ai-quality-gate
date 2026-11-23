"""M6: quality-gate.yml and the aqg CLI, end to end on the real M2 fixtures.

Each test builds a small project folder (config + copied result files) in a
temporary directory. Nothing here starts the server or opens a database.
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from aqg.cli import EXIT_BLOCK, EXIT_CONFIG, EXIT_INPUT, EXIT_OK, main

FIXTURES = Path(__file__).parent / "fixtures" / "junit"
BACKEND_DIR = Path(__file__).resolve().parents[2]
LENIENT = {
    "on_optional_failed": "ignore",
    "on_optional_error": "ignore",
    "on_optional_skipped": "ignore",
    "on_flaky": "ignore",
}


@pytest.fixture(autouse=True)
def _no_github_env(monkeypatch):
    for name in (
        "GITHUB_SHA",
        "GITHUB_REF_TYPE",
        "GITHUB_REF_NAME",
        "GITHUB_ACTOR",
        "GITHUB_STEP_SUMMARY",
    ):
        monkeypatch.delenv(name, raising=False)


def _project(tmp_path: Path, policy: dict | None = None, **overrides) -> Path:
    """A project folder with the three real reports and a quality-gate.yml."""
    reports = tmp_path / "reports"
    reports.mkdir(exist_ok=True)
    for name in ("pytest.xml", "vitest.xml", "playwright.xml"):
        shutil.copy(FIXTURES / name, reports / name)
    config = {
        "version": 1,
        "project": "steplab",
        "inputs": [
            {"type": "junit", "path": "reports/pytest.xml", "suite": "backend"},
            {"type": "junit", "path": "reports/vitest.xml", "suite": "unit"},
            {"type": "junit", "path": "reports/playwright.xml", "suite": "e2e"},
        ],
    }
    if policy is not None:
        config["policy"] = policy
    config.update(overrides)
    path = tmp_path / "quality-gate.yml"
    path.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def _check(config: Path, *extra: str) -> int:
    return main(["check", "--config", str(config), *extra])


def _report(config: Path) -> dict:
    return json.loads((config.parent / "aqg-report" / "report.json").read_text(encoding="utf-8"))


# --- aqg check: decisions and exit codes ------------------------------------------------


def test_check_on_the_three_fixtures_blocks_with_exit_1(tmp_path, capsys):
    """M6 acceptance: the expected decision and exit code, with no server running."""
    config = _project(tmp_path)
    assert _check(config) == EXIT_BLOCK
    report = _report(config)
    assert report["decision"]["status"] == "block"
    assert report["decision"]["counts"] == {
        "total": 23,
        "passed": 11,
        "failed": 4,
        "skipped": 6,
        "error": 2,
        "flaky": 1,
    }
    assert [i["source"] for i in report["inputs"]] == ["pytest", "vitest", "playwright"]
    # Paths as written in quality-gate.yml, not absolute paths on this machine.
    expected_paths = ["reports/pytest.xml", "reports/vitest.xml", "reports/playwright.xml"]
    assert [i["path"] for i in report["inputs"]] == expected_paths
    assert [i["path"] for i in report["run"]["inputs"]] == expected_paths
    out = capsys.readouterr().out
    assert out.startswith("Quality gate: BLOCK for steplab")
    assert "BLOCK: 4 optional checks failed" in out
    summary = (tmp_path / "aqg-report" / "summary.md").read_text(encoding="utf-8")
    assert summary.startswith("## Quality gate: ⛔ BLOCK")
    assert "No baseline is configured" in summary


def test_check_passes_with_exit_0(tmp_path):
    config = _project(tmp_path, LENIENT)
    assert _check(config) == EXIT_OK
    assert _report(config)["decision"]["status"] == "pass"


def test_warn_exits_0_when_fail_on_warn_is_off(tmp_path):
    config = _project(tmp_path, {**LENIENT, "on_flaky": "warn"})
    assert _check(config) == EXIT_OK
    assert _report(config)["decision"]["status"] == "warn"
    summary = (tmp_path / "aqg-report" / "summary.md").read_text(encoding="utf-8")
    assert "Warnings don't fail CI" in summary


def test_warn_exits_1_when_fail_on_warn_is_on(tmp_path):
    config = _project(tmp_path, {**LENIENT, "on_flaky": "warn", "fail_on_warn": True})
    assert _check(config) == EXIT_BLOCK
    assert _report(config)["decision"]["status"] == "warn"


def test_required_pattern_from_config(tmp_path):
    config = _project(tmp_path, {**LENIENT, "required": ["e2e::*keeps code blocks"]})
    assert _check(config) == EXIT_BLOCK
    assert _report(config)["decision"]["blocking"] == [
        "1 required check failed: e2e::export.spec.ts::export › keeps code blocks"
    ]


def test_min_checks_blocks(tmp_path):
    config = _project(tmp_path, LENIENT)
    data = yaml.safe_load(config.read_text(encoding="utf-8"))
    data["inputs"][2]["min_checks"] = 50
    config.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    assert _check(config) == EXIT_BLOCK
    assert "7 tests found, fewer than min_checks 50" in _report(config)["decision"]["blocking"][0]


def test_glob_input_reads_every_matching_file(tmp_path):
    config = _project(
        tmp_path,
        LENIENT,
        inputs=[{"type": "junit", "path": "reports/**/*.xml", "suite": "all", "source": "vitest"}],
    )
    # Three files, same suite label: their ids differ by classname, except none clash here.
    (tmp_path / "reports" / "pytest.xml").unlink()
    (tmp_path / "reports" / "playwright.xml").unlink()
    nested = tmp_path / "reports" / "shard2"
    nested.mkdir()
    text = (FIXTURES / "vitest.xml").read_text(encoding="utf-8")
    (nested / "vitest.xml").write_text(text.replace("src/sample.spec.ts", "src/other.spec.ts"))
    assert _check(config) == EXIT_OK
    assert len(_report(config)["inputs"]) == 2


def test_duplicate_ids_can_be_numbered_from_config(tmp_path):
    shutil.copy(FIXTURES / "playwright-two-projects.xml", tmp_path / "two.xml")
    base = {"version": 1, "project": "p", "inputs": [{"type": "junit", "path": "two.xml"}]}
    config = tmp_path / "quality-gate.yml"
    config.write_text(yaml.safe_dump(base), encoding="utf-8")
    assert _check(config) == EXIT_INPUT
    base["policy"] = {"duplicate_ids": "number"}
    config.write_text(yaml.safe_dump(base), encoding="utf-8")
    assert _check(config) == EXIT_OK
    assert "numbered as" in _report(config)["notes"][0]


def test_paths_are_relative_to_the_config_file(tmp_path, monkeypatch):
    config = _project(tmp_path, LENIENT)
    monkeypatch.chdir(tmp_path.parent)
    assert _check(config) == EXIT_OK
    assert (tmp_path / "aqg-report" / "report.json").exists()


def test_output_flag_overrides_the_config(tmp_path):
    config = _project(tmp_path, LENIENT)
    assert _check(config, "--output", str(tmp_path / "elsewhere")) == EXIT_OK
    assert (tmp_path / "elsewhere" / "report.json").exists()


# --- run details ---------------------------------------------------------------------------


def test_version_and_commit_from_flags(tmp_path):
    config = _project(tmp_path, LENIENT)
    _check(config, "--version", "1.4.0", "--commit", "abc1234")
    run = _report(config)["run"]
    assert (run["version"], run["commit"]) == ("1.4.0", "abc1234")


def test_version_and_commit_from_github_on_a_tag(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "f" * 40)
    monkeypatch.setenv("GITHUB_REF_TYPE", "tag")
    monkeypatch.setenv("GITHUB_REF_NAME", "v1.4.0")
    config = _project(tmp_path, LENIENT)
    _check(config)
    run = _report(config)["run"]
    assert (run["version"], run["commit"]) == ("v1.4.0", "f" * 40)


def test_branch_builds_have_no_version(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_REF_TYPE", "branch")
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    config = _project(tmp_path, LENIENT)
    _check(config)
    assert _report(config)["run"]["version"] is None


def test_flags_win_over_github_variables(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "f" * 40)
    config = _project(tmp_path, LENIENT)
    _check(config, "--commit", "abc1234")
    assert _report(config)["run"]["commit"] == "abc1234"


def test_github_run_summary_is_written(tmp_path, monkeypatch):
    target = tmp_path / "step-summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(target))
    config = _project(tmp_path)
    _check(config)
    assert target.read_text(encoding="utf-8").startswith("## Quality gate: ⛔ BLOCK")


def test_github_run_summary_shows_input_errors(tmp_path, monkeypatch):
    target = tmp_path / "step-summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(target))
    config = _project(tmp_path)
    (tmp_path / "reports" / "vitest.xml").unlink()
    assert _check(config) == EXIT_INPUT
    text = target.read_text(encoding="utf-8")
    assert "input error" in text and "result file not found" in text


# --- input errors: exit 3 ------------------------------------------------------------------


def test_missing_result_file_exits_3(tmp_path, capsys):
    config = _project(tmp_path)
    (tmp_path / "reports" / "playwright.xml").unlink()
    assert _check(config) == EXIT_INPUT
    assert "result file not found" in capsys.readouterr().err
    assert not (tmp_path / "aqg-report" / "report.json").exists()


def test_truncated_result_file_exits_3(tmp_path):
    config = _project(tmp_path)
    path = tmp_path / "reports" / "vitest.xml"
    path.write_text(path.read_text(encoding="utf-8")[:600], encoding="utf-8")
    assert _check(config) == EXIT_INPUT


def test_glob_matching_nothing_exits_3(tmp_path, capsys):
    config = _project(tmp_path, inputs=[{"type": "junit", "path": "reports/e2e/*.xml"}])
    assert _check(config) == EXIT_INPUT
    assert "no result files match this pattern" in capsys.readouterr().err


# --- config errors: exit 2 -----------------------------------------------------------------


HEAD = "version: 1\nproject: p\n"
ONE_INPUT = HEAD + "inputs: [{type: junit, path: a.xml}]\n"
BAD_CONFIGS = {
    "not yaml": "version: 1\nproject: [unclosed\n",
    "empty": "",
    "a list": "- version: 1\n",
    "wrong version": ONE_INPUT.replace("version: 1", "version: 2"),
    "no inputs": HEAD + "inputs: []\n",
    "unknown key": ONE_INPUT + "baseline_path: x\n",
    "typo in policy": ONE_INPUT + "policy: {on_mising: warn}\n",
    "bad action": ONE_INPUT + "policy: {on_missing: fail}\n",
    "yes/no action": ONE_INPUT + "policy: {on_missing: no}\n",
    "unknown input type": HEAD + "inputs: [{type: quality-checker, path: a}]\n",
    "llm source": HEAD + "inputs: [{type: junit, path: a.xml, source: llm}]\n",
    "min_checks as text": HEAD + "inputs: [{type: junit, path: a, min_checks: '3'}]\n",
    "blank project": ONE_INPUT.replace("project: p", "project: ' '"),
}


@pytest.mark.parametrize("case", sorted(BAD_CONFIGS))
def test_bad_config_exits_2_for_every_command(tmp_path, case, capsys):
    config = tmp_path / "quality-gate.yml"
    config.write_text(BAD_CONFIGS[case], encoding="utf-8")
    assert main(["validate", "--config", str(config)]) == EXIT_CONFIG
    assert _check(config) == EXIT_CONFIG
    assert "aqg: error:" in capsys.readouterr().err


def test_missing_config_exits_2(tmp_path, capsys):
    assert main(["validate", "--config", str(tmp_path / "nope.yml")]) == EXIT_CONFIG
    assert "config file not found" in capsys.readouterr().err


def test_config_error_names_the_bad_key(tmp_path, capsys):
    config = tmp_path / "quality-gate.yml"
    config.write_text(BAD_CONFIGS["typo in policy"], encoding="utf-8")
    main(["validate", "--config", str(config)])
    assert "policy.on_mising" in capsys.readouterr().err


def test_unknown_command_or_flag_exits_2(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["deploy"])
    assert exc.value.code == 2


# --- aqg validate ----------------------------------------------------------------------------


def test_validate_checks_only_the_config(tmp_path, capsys):
    config = _project(tmp_path, {"required": ["e2e::*"]})
    shutil.rmtree(tmp_path / "reports")  # result files aren't needed to validate
    assert main(["validate", "--config", str(config)]) == EXIT_OK
    assert "is valid: project steplab, 3 input(s), 1 required pattern(s), baseline: none" in (
        capsys.readouterr().out
    )


# --- baselines --------------------------------------------------------------------------------


def _with_baseline(tmp_path: Path, policy: dict | None = None, **baseline) -> Path:
    return _project(
        tmp_path,
        LENIENT if policy is None else policy,
        baseline={"path": "quality/baseline.json", **baseline},
    )


def _approve(config: Path, *extra: str) -> int:
    report = config.parent / "aqg-report" / "report.json"
    return main(["baseline", "approve", "--config", str(config), "--report", str(report), *extra])


def test_missing_baseline_file_exits_2_with_how_to_fix(tmp_path, capsys):
    config = _with_baseline(tmp_path)
    assert _check(config) == EXIT_CONFIG
    assert "aqg baseline approve" in capsys.readouterr().err


def test_approve_then_check_shows_no_changes(tmp_path, capsys):
    config = _project(tmp_path, LENIENT)
    assert _check(config) == EXIT_OK
    config = _with_baseline(tmp_path)
    assert _approve(config, "--approved-by", "deepa") == EXIT_OK
    assert "Commit it in a reviewed PR" in capsys.readouterr().out
    baseline = json.loads((tmp_path / "quality" / "baseline.json").read_text(encoding="utf-8"))
    assert baseline["approved_by"] == "deepa" and baseline["counts"]["total"] == 23

    assert _check(config) == EXIT_OK
    report = _report(config)
    assert report["baseline"]["approved_by"] == "deepa"
    assert report["regressions"] is not None
    summary = (tmp_path / "aqg-report" / "summary.md").read_text(encoding="utf-8")
    assert "No changes." in summary


def _approved(tmp_path: Path, **baseline) -> Path:
    config = _project(tmp_path, LENIENT)
    _check(config)
    config = _with_baseline(tmp_path, **baseline)
    assert _approve(config, "--approved-by", "deepa") == EXIT_OK
    return config


def test_new_failure_since_the_baseline_blocks(tmp_path):
    config = _approved(tmp_path)
    path = tmp_path / "reports" / "vitest.xml"
    text = path.read_text(encoding="utf-8")
    case = 'name="markdown export &gt; renders headings" time="0.003437724">'
    assert case in text
    path.write_text(
        text.replace(case, case + '\n            <failure message="broke"/>').replace(
            'failures="2"', 'failures="3"', 1
        ),
        encoding="utf-8",
    )
    assert _check(config) == EXIT_BLOCK
    report = _report(config)
    assert report["regressions"]["new_failures"] == [
        "unit::src/sample.spec.ts::markdown export > renders headings"
    ]
    summary = (tmp_path / "aqg-report" / "summary.md").read_text(encoding="utf-8")
    assert "**New failures (1)**" in summary


def test_removed_test_warns(tmp_path):
    config = _approved(tmp_path)
    path = tmp_path / "reports" / "playwright.xml"
    text = path.read_text(encoding="utf-8")
    start = text.index('<testcase name="export › downloads HTML"')
    end = text.index("</testcase>", start) + len("</testcase>")
    path.write_text((text[:start] + text[end:]).replace('tests="7"', 'tests="6"'), encoding="utf-8")
    assert _check(config) == EXIT_OK
    assert _report(config)["decision"]["status"] == "warn"
    assert _report(config)["regressions"]["removed"] == [
        "e2e::export.spec.ts::export › downloads HTML"
    ]


def test_confirmed_rename_from_config(tmp_path):
    old, new = (
        "e2e::export.spec.ts::export › downloads HTML",
        "e2e::export.spec.ts::export › saves HTML",
    )
    config = _approved(tmp_path, renames={old: new})
    path = tmp_path / "reports" / "playwright.xml"
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace("export › downloads HTML", "export › saves HTML"), encoding="utf-8"
    )
    assert _check(config) == EXIT_OK
    report = _report(config)
    assert report["decision"]["status"] == "pass"
    assert report["regressions"]["renamed"] == [
        {
            "old": "e2e::export.spec.ts::export › downloads HTML",
            "new": "e2e::export.spec.ts::export › saves HTML",
        }
    ]


def test_corrupt_baseline_exits_2(tmp_path, capsys):
    config = _approved(tmp_path)
    (tmp_path / "quality" / "baseline.json").write_text("{", encoding="utf-8")
    assert _check(config) == EXIT_CONFIG
    assert "not a valid baseline file" in capsys.readouterr().err


def test_approve_refuses_a_block_report(tmp_path, capsys):
    config = _project(tmp_path)
    assert _check(config) == EXIT_BLOCK
    config = _with_baseline(tmp_path, policy={})
    assert _approve(config, "--approved-by", "deepa", "--allow-warn") == EXIT_BLOCK
    assert "BLOCK run can't be approved" in capsys.readouterr().err
    assert not (tmp_path / "quality" / "baseline.json").exists()


def test_approve_needs_allow_warn_for_a_warn_report(tmp_path):
    config = _project(tmp_path, {**LENIENT, "on_flaky": "warn"})
    assert _check(config) == EXIT_OK
    config = _with_baseline(tmp_path)
    assert _approve(config, "--approved-by", "deepa") == EXIT_BLOCK
    assert _approve(config, "--approved-by", "deepa", "--allow-warn") == EXIT_OK


def test_approve_needs_to_know_who_approves(tmp_path, monkeypatch, capsys):
    config = _project(tmp_path, LENIENT)
    _check(config)
    config = _with_baseline(tmp_path)
    assert _approve(config) == EXIT_CONFIG
    assert "--approved-by" in capsys.readouterr().err
    monkeypatch.setenv("GITHUB_ACTOR", "sdkdeepa")
    assert _approve(config) == EXIT_OK
    baseline = json.loads((tmp_path / "quality" / "baseline.json").read_text(encoding="utf-8"))
    assert baseline["approved_by"] == "sdkdeepa"


def test_approve_with_missing_or_broken_report_exits_3(tmp_path):
    config = _with_baseline(tmp_path)
    assert _approve(config, "--approved-by", "deepa") == EXIT_INPUT  # no report yet
    (tmp_path / "aqg-report").mkdir()
    (tmp_path / "aqg-report" / "report.json").write_text('{"decision": 1}', encoding="utf-8")
    assert _approve(config, "--approved-by", "deepa") == EXIT_INPUT


def test_approve_refuses_a_report_for_another_project(tmp_path, capsys):
    config = _project(tmp_path, LENIENT)
    _check(config)
    config = _project(
        tmp_path, LENIENT, project="other", baseline={"path": "quality/baseline.json"}
    )
    assert _approve(config, "--approved-by", "deepa") == EXIT_CONFIG
    assert "is for project 'steplab'" in capsys.readouterr().err


def test_approve_without_baseline_path_exits_2(tmp_path, capsys):
    config = _project(tmp_path, LENIENT)
    _check(config)
    assert _approve(config, "--approved-by", "deepa") == EXIT_CONFIG
    assert "no baseline.path" in capsys.readouterr().err


# --- Markdown safety ---------------------------------------------------------------------------


def test_summary_keeps_odd_test_names_literal(tmp_path):
    xml = (
        '<testsuites name="vitest tests" tests="1"><testsuite name="s" tests="1">'
        '<testcase classname="c" name="a | b &lt;img src=x&gt; `tick` **bold**">'
        '<failure message="no"/></testcase></testsuite></testsuites>'
    )
    (tmp_path / "odd.xml").write_text(xml, encoding="utf-8")
    config = tmp_path / "quality-gate.yml"
    config.write_text(
        yaml.safe_dump(
            {"version": 1, "project": "p", "inputs": [{"type": "junit", "path": "odd.xml"}]}
        ),
        encoding="utf-8",
    )
    assert _check(config) == EXIT_BLOCK
    summary = (tmp_path / "aqg-report" / "summary.md").read_text(encoding="utf-8")
    assert re.search(r"(?<!\\)<img", summary) is None  # never raw HTML
    assert "\\<img src=x\\>" in summary
    assert "\\| b" in summary


# --- separate processes ---------------------------------------------------------------------


FORBIDDEN = (
    "app",
    "fastapi",
    "starlette",
    "uvicorn",
    "sqlite3",
    "_sqlite3",
    "opentelemetry",
    "openinference",
    "phoenix",
    "langchain",
    "langchain_core",
    "langchain_community",
    "langchain_openai",
    "langchain_chroma",
    "langchain_text_splitters",
    "chromadb",
    "ragas",
    "deepeval",
    "openai",
    "google.genai",
)

PROBE = """
import json, sys
from aqg.cli import main
code = main(["check", "--config", sys.argv[1]])
print(json.dumps({"code": code, "modules": sorted(sys.modules)}))
"""


def test_cli_process_loads_no_server_tracing_langchain_or_sqlite(tmp_path):
    config = _project(tmp_path)
    result = subprocess.run(
        [sys.executable, "-c", PROBE, str(config)],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        timeout=120,
    )
    data = json.loads(result.stdout.strip().splitlines()[-1])
    assert data["code"] == EXIT_BLOCK
    assert "aqg.cli" in data["modules"] and "yaml" in data["modules"]
    loaded = [m for m in data["modules"] if any(m == p or m.startswith(p + ".") for p in FORBIDDEN)]
    assert loaded == []


def test_python_dash_m_aqg_returns_the_exit_code(tmp_path):
    config = _project(tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", "aqg", "check", "--config", str(config)],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == EXIT_BLOCK
    assert result.stdout.startswith("Quality gate: BLOCK for steplab")


def test_installed_aqg_command_works(tmp_path):
    command = Path(sys.executable).parent / "aqg"
    if not command.exists():
        pytest.skip("the aqg command isn't installed in this environment (run uv sync)")
    config = _project(tmp_path, LENIENT)
    result = subprocess.run(
        [str(command), "check", "--config", str(config)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == EXIT_OK
    version = subprocess.run([str(command), "--version"], capture_output=True, text=True)
    assert version.stdout.startswith("aqg ")
