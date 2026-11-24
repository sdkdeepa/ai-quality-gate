"""M8: the GitHub Action (action.yml), its check script, and the gate's own
quality-gate.yml. Needs only the core, so it also runs in the core-only job.

GitHub runs the action itself in pr.yml ("GitHub Action test" and "Quality
gate (self-check)"); these tests cover what can be checked without GitHub.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from aqg.cli import EXIT_OK, main, tool_version

REPO = Path(__file__).resolve().parents[3]
ACTION = REPO / "action.yml"
SCRIPT = REPO / "scripts" / "action_check.sh"
FIXTURES = Path(__file__).parent / "fixtures"
BIN = Path(sys.executable).parent  # has python and the installed aqg command
SHA_PIN = re.compile(r"^[\w.-]+/[\w.-]+@[0-9a-f]{40}$")


def _action() -> dict:
    return yaml.safe_load(ACTION.read_text(encoding="utf-8"))


def _steps() -> list[dict]:
    return _action()["runs"]["steps"]


# --- action.yml ---------------------------------------------------------------------------


def test_action_is_composite_with_the_documented_inputs_and_outputs():
    action = _action()
    assert action["runs"]["using"] == "composite"
    assert set(action["inputs"]) == {
        "config",
        "working-directory",
        "version",
        "commit",
        "output",
        "upload-report",
        "artifact-name",
        "python-version",
    }
    assert action["inputs"]["config"]["default"] == "quality-gate.yml"
    assert set(action["outputs"]) == {"decision", "exit-code", "report-dir"}


def test_every_action_the_action_uses_is_pinned_by_commit_sha():
    """People who pin this action by SHA get every action it pulls in pinned too."""
    uses = [s["uses"] for s in _steps() if "uses" in s]
    assert uses
    assert all(SHA_PIN.match(u) for u in uses), uses


def test_aqg_is_installed_from_the_actions_own_checkout():
    install = next(s for s in _steps() if s.get("name") == "Install aqg from this action's version")
    assert '"$GITHUB_ACTION_PATH/backend"' in install["run"]
    assert "git+" not in install["run"]  # no second download of some other version


def test_setup_python_leaves_the_jobs_python_alone():
    python = next(s for s in _steps() if s.get("id") == "python")
    assert python["with"]["update-environment"] is False


def test_action_never_touches_secrets_or_tokens():
    text = ACTION.read_text(encoding="utf-8")
    assert "secrets." not in text
    assert "github.token" not in text and "GITHUB_TOKEN" not in text


def test_last_step_passes_on_the_gates_exit_code():
    last = _steps()[-1]
    assert last["env"]["CODE"] == "${{ steps.check.outputs.exit-code }}"
    assert last["run"] == 'exit "${CODE:-3}"'  # no result at all is an input error


def test_report_is_uploaded_only_when_one_was_written():
    upload = next(s for s in _steps() if s.get("name") == "Upload the report")
    assert "steps.check.outputs.report-dir != ''" in upload["if"]
    assert upload["with"]["if-no-files-found"] == "ignore"


# --- scripts/action_check.sh ---------------------------------------------------------------


def _run_script(tmp_path: Path, config: Path, cwd: Path | None = None, **env) -> dict:
    outputs = tmp_path / "github-output"
    outputs.write_text("", encoding="utf-8")
    result = subprocess.run(
        ["bash", str(SCRIPT), str(BIN)],
        cwd=cwd or REPO,
        env={
            "PATH": f"{BIN}:/usr/bin:/bin",
            "GITHUB_OUTPUT": str(outputs),
            "AQG_CONFIG": str(config),
            "AQG_VERSION": env.get("version", ""),
            "AQG_COMMIT": env.get("commit", "abc1234"),
            "AQG_OUTPUT": env.get("output", ""),
        },
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr  # the script itself never fails the step
    lines = outputs.read_text(encoding="utf-8").splitlines()
    return dict(line.split("=", 1) for line in lines)


@pytest.fixture
def blocking(tmp_path) -> Path:
    return FIXTURES / "action" / "blocking.yml"


def test_script_reports_block(tmp_path, blocking):
    out = _run_script(tmp_path, blocking, output=str(tmp_path / "report"))
    assert out == {
        "exit-code": "1",
        "decision": "block",
        "report-dir": str(tmp_path / "report"),
    }
    assert (tmp_path / "report" / "summary.md").exists()


def test_script_reports_pass_with_version(tmp_path):
    out = _run_script(
        tmp_path,
        FIXTURES / "action" / "passing.yml",
        output=str(tmp_path / "report"),
        version="v1.0.0",
    )
    assert (out["exit-code"], out["decision"]) == ("0", "pass")
    report = (tmp_path / "report" / "report.json").read_text(encoding="utf-8")
    assert '"version": "v1.0.0"' in report


def test_script_uses_the_configs_output_dir_and_returns_an_absolute_path(tmp_path):
    project = tmp_path / "project"
    (project / "reports").mkdir(parents=True)
    (project / "reports" / "vitest.xml").write_bytes(
        (FIXTURES / "junit" / "vitest.xml").read_bytes()
    )
    (project / "quality-gate.yml").write_text(
        "version: 1\nproject: p\ninputs: [{type: junit, path: reports/vitest.xml}]\n"
        "policy: {on_optional_failed: ignore, on_optional_skipped: ignore}\n"
        "output: {dir: out/gate}\n",
        encoding="utf-8",
    )
    out = _run_script(tmp_path, Path("quality-gate.yml"), cwd=project)
    assert out["report-dir"] == str(project / "out" / "gate")
    assert Path(out["report-dir"]).is_absolute()


def test_relative_output_input_comes_back_absolute(tmp_path):
    """upload-artifact resolves paths from the workspace, not working-directory."""
    work = tmp_path / "sub"
    work.mkdir()
    out = _run_script(tmp_path, FIXTURES / "action" / "passing.yml", cwd=work, output="gate-out")
    assert out["report-dir"] == str(work / "gate-out")


def test_script_config_error_has_no_decision_or_report(tmp_path):
    bad = tmp_path / "bad.yml"
    bad.write_text("version: 2\n", encoding="utf-8")
    assert _run_script(tmp_path, bad) == {"exit-code": "2", "decision": "", "report-dir": ""}


def test_script_input_error_has_no_decision_or_report(tmp_path):
    config = tmp_path / "quality-gate.yml"
    config.write_text(
        "version: 1\nproject: p\ninputs: [{type: junit, path: missing.xml}]\n", encoding="utf-8"
    )
    assert _run_script(tmp_path, config) == {"exit-code": "3", "decision": "", "report-dir": ""}


def test_script_ignores_a_stale_report_after_an_input_error(tmp_path):
    config = tmp_path / "quality-gate.yml"
    config.write_text(
        "version: 1\nproject: p\ninputs: [{type: junit, path: missing.xml}]\n", encoding="utf-8"
    )
    stale = tmp_path / "aqg-report"
    stale.mkdir()
    (stale / "report.json").write_text('{"decision": {"status": "pass"}}', encoding="utf-8")
    out = _run_script(tmp_path, config)
    assert out == {"exit-code": "3", "decision": "", "report-dir": ""}


# --- the gate's own config and release ------------------------------------------------------


def test_the_gates_own_quality_gate_yml_is_valid(capsys):
    assert main(["validate", "--config", str(REPO / "quality-gate.yml")]) == EXIT_OK
    assert "3 input(s), 1 required pattern(s)" in capsys.readouterr().out


def test_action_test_configs_are_valid():
    for name in ("blocking.yml", "passing.yml"):
        assert main(["validate", "--config", str(FIXTURES / "action" / name)]) == EXIT_OK


def test_version_matches_the_release():
    pyproject = (REPO / "backend" / "pyproject.toml").read_text(encoding="utf-8")
    version = re.search(r'^version = "([^"]+)"$', pyproject, re.MULTILINE).group(1)
    assert version == "1.0.0"
    assert tool_version() in (version, "unknown")
    changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## {version} " in changelog
