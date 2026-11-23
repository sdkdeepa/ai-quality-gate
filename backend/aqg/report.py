"""report.json and summary.md (M6).

report.json holds everything behind a decision: the full evidence run, the
decision, the baseline comparison and import notes. ``aqg baseline approve``
reads it back. summary.md is the same result for people, and is also written
to the GitHub Actions run summary.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from aqg.baseline import RegressionReport
from aqg.evidence import EvidenceRun
from aqg.evidence.models import NonBlankStr
from aqg.policy import EvidenceDecision, GateStatus

REPORT_SCHEMA_VERSION = "1"
MAX_IDS_IN_SUMMARY = 20
_BADGE = {GateStatus.PASS: "✅ PASS", GateStatus.WARN: "⚠️ WARN", GateStatus.BLOCK: "⛔ BLOCK"}


class ReportError(Exception):
    """report.json is missing or broken."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BaselineInfo(_Model):
    path: NonBlankStr
    approved_by: NonBlankStr
    approved_at: AwareDatetime
    commit: NonBlankStr | None = None
    version: NonBlankStr | None = None


class InputSummary(_Model):
    path: NonBlankStr
    source: NonBlankStr
    checks: int


class GateReport(_Model):
    schema_version: Literal["1"] = REPORT_SCHEMA_VERSION
    tool_version: NonBlankStr
    created_at: AwareDatetime
    config: NonBlankStr
    decision: EvidenceDecision
    baseline: BaselineInfo | None = None
    regressions: RegressionReport | None = None
    inputs: list[InputSummary] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    run: EvidenceRun


def write_report(report: GateReport, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "report.json"
    md_path = output_dir / "summary.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(summary_markdown(report), encoding="utf-8")
    return json_path, md_path


def load_report(path: str | Path) -> GateReport:
    path = Path(path)
    if not path.is_file():
        raise ReportError(f"{path}: report not found; run aqg check first")
    try:
        return GateReport.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise ReportError(f"{path}: report can't be read ({exc})") from exc
    except ValidationError as exc:
        raise ReportError(f"{path}: not a valid aqg report ({exc.error_count()} problems)") from exc


# --- Markdown -------------------------------------------------------------------------


def _code(text: str) -> str:
    """Show a test id literally in Markdown, whatever characters it has."""
    text = " ".join(text.split())
    fence = "``" if "`" in text else "`"
    pad = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{fence}{pad}{text}{pad}{fence}"


def _plain(text: str) -> str:
    """Escape a reason line so ids in it can't become HTML or Markdown."""
    text = " ".join(text.split())
    for char in "\\`*_[]<>|#":
        text = text.replace(char, "\\" + char)
    return text


def _id_list(title: str, ids: list[str]) -> list[str]:
    if not ids:
        return []
    lines = [f"**{title} ({len(ids)})**", ""]
    lines += [f"- {_code(i)}" for i in ids[:MAX_IDS_IN_SUMMARY]]
    if len(ids) > MAX_IDS_IN_SUMMARY:
        lines.append(f"- … and {len(ids) - MAX_IDS_IN_SUMMARY} more in report.json")
    return [*lines, ""]


def summary_markdown(report: GateReport) -> str:
    d = report.decision
    run = report.run
    c = d.counts
    details = [f"project **{_plain(run.project)}**"]
    if run.version:
        details.append(f"version {_code(run.version)}")
    if run.commit:
        details.append(f"commit {_code(run.commit[:12])}")
    lines = [f"## Quality gate: {_BADGE[d.status]}", "", " · ".join(details), ""]
    if d.status is GateStatus.WARN:
        lines += [
            "This fails CI because fail_on_warn is on."
            if d.fail_on_warn
            else "Warnings don't fail CI (fail_on_warn is off).",
            "",
        ]

    rate = "n/a" if d.pass_rate is None else f"{d.pass_rate:.1%}"
    lines += [
        "| Total | Passed | Failed | Error | Skipped | Flaky | Pass rate |",
        "|---:|---:|---:|---:|---:|---:|---:|",
        f"| {c.total} | {c.passed} | {c.failed} | {c.error} | {c.skipped} | {c.flaky} | {rate} |",
        "",
    ]
    if d.blocking:
        lines += ["### Blocking", "", *[f"- {_plain(r)}" for r in d.blocking], ""]
    if d.warnings:
        lines += ["### Warnings", "", *[f"- {_plain(r)}" for r in d.warnings], ""]

    lines += ["### Changes since the baseline", ""]
    if report.baseline is None:
        lines += ["No baseline is configured, so changes weren't checked.", ""]
    else:
        b = report.baseline
        approved = f"approved by {_plain(b.approved_by)} on {b.approved_at:%Y-%m-%d}"
        lines += [f"Baseline {_code(b.path)}, {approved}.", ""]
        r = report.regressions or RegressionReport()
        if not r.has_changes:
            lines += ["No changes.", ""]
        lines += _id_list("New failures", r.new_failures)
        lines += _id_list("New tests failing", r.new_failing)
        lines += _id_list("Required tests now skipped", r.skipped_required)
        lines += _id_list("Removed tests", r.removed)
        lines += _id_list("Renamed (confirmed)", [f"{x.old} → {x.new}" for x in r.renamed])
        lines += _id_list(
            "Possible renames (confirm under baseline.renames)",
            [f"{x.old} → {x.new}" for x in r.possible_renames],
        )
        lines += _id_list("Recovered", r.recovered)
        lines += _id_list("Added", r.added)

    flaky = [x.id for x in run.checks if x.status == "passed" and "flaky" in x.tags]
    lines += _id_list("Flaky (passed only after a retry)", flaky)

    lines += ["### Inputs", ""]
    lines += [f"- {_code(i.path)}: {i.source}, {i.checks} checks" for i in report.inputs]
    lines.append("")
    if report.notes:
        lines += ["### Notes", "", *[f"- {_plain(n)}" for n in report.notes], ""]
    lines.append(f"<sub>aqg {_plain(report.tool_version)}</sub>")
    return "\n".join(lines) + "\n"
