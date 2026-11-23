"""The aqg command (M6). Runs with no server, database, model or dashboard.

    aqg check [--config quality-gate.yml] [--version V] [--commit SHA] [--output DIR]
    aqg baseline approve --report aqg-report/report.json [--approved-by NAME] [--allow-warn]
    aqg validate [--config quality-gate.yml]

Exit codes:
    0  PASS, or WARN when fail_on_warn is off (also: validate OK, baseline approved)
    1  BLOCK, or WARN when fail_on_warn is on (also: baseline approval refused)
    2  config error: quality-gate.yml, or the baseline file it points to
    3  input error: result files or report.json missing or broken
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

from aqg.baseline import (
    BaselineError,
    apply_regressions,
    approve_baseline,
    compare_to_baseline,
    load_baseline,
    write_baseline,
)
from aqg.config import DEFAULT_CONFIG, ConfigError, LoadedConfig, load_config
from aqg.importers import JUnitInputError, import_junit
from aqg.policy import decide
from aqg.report import (
    BaselineInfo,
    GateReport,
    InputSummary,
    ReportError,
    load_report,
    summary_markdown,
    write_report,
)

EXIT_OK = 0
EXIT_BLOCK = 1
EXIT_CONFIG = 2
EXIT_INPUT = 3


def tool_version() -> str:
    try:
        return metadata.version("ai-quality-gate")
    except metadata.PackageNotFoundError:
        return "unknown"


def _err(message: str) -> None:
    print(f"aqg: error: {message}", file=sys.stderr)


def _github_summary(text: str) -> None:
    """Append to the GitHub Actions run summary when running there."""
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if not target:
        return
    try:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(text if text.endswith("\n") else text + "\n")
    except OSError as exc:
        _err(f"couldn't write the GitHub run summary ({exc})")


def _run_details(args: argparse.Namespace) -> tuple[str | None, str | None]:
    """Version and commit: flags first, then GitHub's own variables."""
    version = args.version
    if version is None and os.environ.get("GITHUB_REF_TYPE") == "tag":
        version = os.environ.get("GITHUB_REF_NAME") or None
    commit = args.commit or os.environ.get("GITHUB_SHA") or None
    return version, commit


def _fail(code: int, message: str, title: str) -> int:
    _err(message)
    _github_summary(f"## Quality gate: ⛔ {title}\n\n```\n{message}\n```\n")
    return code


# --- aqg check ---------------------------------------------------------------------------


def _check(args: argparse.Namespace) -> int:
    try:
        loaded = load_config(args.config)
    except ConfigError as exc:
        return _fail(EXIT_CONFIG, str(exc), "config error")
    cfg = loaded.config
    version, commit = _run_details(args)

    try:
        imported = import_junit(
            loaded.junit_inputs(),
            project=cfg.project,
            version=version,
            commit=commit,
            duplicates=cfg.policy.duplicate_ids,
        )
    except JUnitInputError as exc:
        return _fail(EXIT_INPUT, str(exc), "input error")

    # Record input paths as written in quality-gate.yml, not as absolute paths
    # on this machine, so reports from CI and laptops compare cleanly.
    run = imported.run.model_copy(
        update={
            "inputs": [
                i.model_copy(update={"path": loaded.display(i.path)}) for i in imported.run.inputs
            ]
        }
    )
    decision = decide(run, cfg.policy.evidence_policy(), input_blockers=imported.blockers)

    baseline_info = regressions = None
    if loaded.baseline_path is not None:
        try:
            baseline = load_baseline(loaded.baseline_path)
            regressions = compare_to_baseline(
                run,
                baseline,
                required=cfg.policy.required,
                renames=cfg.baseline.renames,
            )
        except BaselineError as exc:
            return _fail(EXIT_CONFIG, str(exc), "baseline error")
        decision = apply_regressions(decision, regressions, cfg.policy.regressions)
        baseline_info = BaselineInfo(
            path=cfg.baseline.path,
            approved_by=baseline.approved_by,
            approved_at=baseline.approved_at,
            commit=baseline.commit,
            version=baseline.version,
        )

    report = GateReport(
        tool_version=tool_version(),
        created_at=datetime.now(UTC),
        config=str(args.config),
        decision=decision,
        baseline=baseline_info,
        regressions=regressions,
        inputs=[
            InputSummary(
                path=loaded.display(r.input.path), source=r.source.value, checks=len(r.checks)
            )
            for r in imported.reports
        ],
        notes=list(imported.warnings),
        run=run,
    )
    output_dir = Path(args.output) if args.output else loaded.output_dir
    json_path, md_path = write_report(report, output_dir)
    _github_summary(summary_markdown(report))

    c = decision.counts
    print(f"Quality gate: {decision.status.value.upper()} for {cfg.project}")
    print(
        f"  {c.total} checks: {c.passed} passed, {c.failed} failed, {c.error} error, "
        f"{c.skipped} skipped, {c.flaky} flaky"
    )
    for reason in decision.blocking:
        print(f"  BLOCK: {reason}")
    for reason in decision.warnings:
        print(f"  WARN:  {reason}")
    print(f"  Report: {json_path}  Summary: {md_path}")
    return EXIT_BLOCK if decision.fails_ci else EXIT_OK


# --- aqg baseline approve ----------------------------------------------------------------


def _approve(args: argparse.Namespace) -> int:
    try:
        loaded = load_config(args.config)
    except ConfigError as exc:
        return _fail(EXIT_CONFIG, str(exc), "config error")
    target = Path(args.output) if args.output else loaded.baseline_path
    if target is None:
        _err(
            "quality-gate.yml has no baseline.path; add one (for example "
            "quality/baseline.json) or pass --output"
        )
        return EXIT_CONFIG
    approved_by = args.approved_by or os.environ.get("GITHUB_ACTOR")
    if not approved_by or not approved_by.strip():
        _err("say who is approving this baseline with --approved-by NAME")
        return EXIT_CONFIG
    try:
        report = load_report(args.report)
    except ReportError as exc:
        _err(str(exc))
        return EXIT_INPUT
    if report.run.project != loaded.config.project:
        _err(
            f"the report is for project {report.run.project!r}, but quality-gate.yml is for "
            f"{loaded.config.project!r}"
        )
        return EXIT_CONFIG
    try:
        baseline = approve_baseline(
            report.run,
            report.decision,
            approved_by=approved_by.strip(),
            report=str(args.report),
            allow_warn=args.allow_warn,
        )
    except BaselineError as exc:
        _err(str(exc))
        return EXIT_BLOCK
    write_baseline(target, baseline)
    print(
        f"Baseline written to {target}: {baseline.counts.total} checks from a "
        f"{baseline.decision.value.upper()} run, approved by {baseline.approved_by}. "
        "Commit it in a reviewed PR."
    )
    return EXIT_OK


# --- aqg validate -------------------------------------------------------------------------


def _validate(args: argparse.Namespace) -> int:
    try:
        loaded: LoadedConfig = load_config(args.config)
    except ConfigError as exc:
        _err(str(exc))
        return EXIT_CONFIG
    cfg = loaded.config
    baseline = cfg.baseline.path if cfg.baseline else "none"
    print(
        f"{args.config} is valid: project {cfg.project}, {len(cfg.inputs)} input(s), "
        f"{len(cfg.policy.required)} required pattern(s), baseline: {baseline}"
    )
    return EXIT_OK


# --- entry point -------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aqg", description="AI Quality Gate: decide PASS, WARN or BLOCK from test results."
    )
    parser.add_argument("--version", action="version", version=f"aqg {tool_version()}")
    commands = parser.add_subparsers(dest="command", required=True)

    def config_flag(p: argparse.ArgumentParser) -> None:
        p.add_argument("--config", default=DEFAULT_CONFIG, help="default: quality-gate.yml")

    check = commands.add_parser("check", help="import results, decide, compare, write reports")
    config_flag(check)
    check.add_argument("--version", dest="version", help="release version of this run")
    check.add_argument("--commit", help="commit of this run (default: GITHUB_SHA)")
    check.add_argument("--output", help="report folder (default: output.dir in the config)")
    check.set_defaults(func=_check)

    baseline = commands.add_parser("baseline", help="manage the approved baseline")
    baseline_commands = baseline.add_subparsers(dest="baseline_command", required=True)
    approve = baseline_commands.add_parser("approve", help="approve a PASS report as baseline")
    config_flag(approve)
    approve.add_argument("--report", required=True, help="report.json written by aqg check")
    approve.add_argument("--approved-by", help="who approves (default: GITHUB_ACTOR)")
    approve.add_argument("--allow-warn", action="store_true", help="also approve a WARN run")
    approve.add_argument("--output", help="baseline file (default: baseline.path in the config)")
    approve.set_defaults(func=_approve)

    validate = commands.add_parser("validate", help="check quality-gate.yml only")
    config_flag(validate)
    validate.set_defaults(func=_validate)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
