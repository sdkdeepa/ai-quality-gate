"""JUnit XML importer (M2).

Reads JUnit XML written by pytest, Vitest and Playwright and turns it into an
``EvidenceRun``. The test tools keep running exactly as they do today; the gate
only reads their result files.

Mapping
    A ``<testcase>`` with ``<error>`` is error, with ``<failure>`` is failed,
    with ``<skipped>`` is skipped, and with none of these is passed. Nested
    ``<testsuite>`` elements are flattened. The check id is
    ``suite::classname::name``, where suite is the input's suite label if one is
    given, otherwise the enclosing ``<testsuite name>``.

Retries (each tool writes them differently; see tests/aqg/fixtures/junit)
    pytest      Repeated ``<testcase>`` entries with the same id, one after
                another: earlier attempts from pytest-rerunfailures (written as
                empty entries), or a test that failed and then errored in
                teardown. The last entry decides the status. Several entries
                ending in a pass means the test is flaky.
    Vitest      One ``<testcase>`` with a ``<failure>`` per failed attempt. A
                test that passed on retry looks like a plain pass.
    Playwright  Only the final attempt is written. A test that passed on retry
                looks like a plain pass.
    A flaky test is reported as passed with the tag ``flaky``.

Incomplete evidence is never a pass
    Input errors (``JUnitInputError``): a missing, unreadable, empty, oversized,
    truncated or malformed file; a DOCTYPE (refused, to block XML entity
    attacks); a ``tests=`` count that shows test cases are missing; duplicate ids
    (unless numbering is chosen).
    Blockers (returned for the policy to turn into BLOCK): a report with zero
    test cases, or fewer tests than the input's ``min_checks``.

Uses only the standard library and the evidence model.
"""

from __future__ import annotations

import math
import pyexpat
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from aqg.evidence import (
    CheckEvidence,
    CheckSource,
    CheckStatus,
    EvidenceInput,
    EvidenceRun,
    InputFormat,
)

DEFAULT_MAX_BYTES = 50 * 1024 * 1024
MESSAGE_LIMIT = 4000
FLAKY_TAG = "flaky"
_JUNIT_SOURCES = (CheckSource.PYTEST, CheckSource.VITEST, CheckSource.PLAYWRIGHT)


class JUnitInputError(Exception):
    """A result file can't be trusted as evidence (exit code 3 in the M6 CLI)."""

    def __init__(self, path: str | Path, problem: str) -> None:
        self.path = str(path)
        self.problem = problem
        super().__init__(f"{path}: {problem}" if str(path) else problem)


class DuplicateIds(StrEnum):
    """What to do when two different test cases share an id."""

    ERROR = "error"  # default: an input error, so a test can't hide behind another
    NUMBER = "number"  # keep both, the later one gets "#2", "#3"..., with a warning


@dataclass(frozen=True)
class JUnitInput:
    """One JUnit result file to read."""

    path: str | Path
    suite: str | None = None  # label used as the first part of every check id
    source: CheckSource | None = None  # detected from the file when not given
    min_checks: int | None = None  # BLOCK when fewer tests than this are found

    def __post_init__(self) -> None:
        if not str(self.path).strip():
            raise ValueError("path must not be blank")
        if self.suite is not None and (not self.suite.strip() or self.suite != self.suite.strip()):
            raise ValueError("suite must be non-blank, with no leading or trailing spaces")
        if self.source is not None and CheckSource(self.source) not in _JUNIT_SOURCES:
            raise ValueError("source must be pytest, vitest or playwright for JUnit input")
        if self.min_checks is not None and (
            isinstance(self.min_checks, bool)
            or not isinstance(self.min_checks, int)
            or self.min_checks < 1
        ):
            raise ValueError("min_checks must be a whole number of at least 1")


@dataclass(frozen=True)
class JUnitReport:
    """What one result file contained."""

    input: EvidenceInput
    source: CheckSource
    checks: tuple[CheckEvidence, ...]
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()


@dataclass(frozen=True)
class JUnitImport:
    """All result files combined into one evidence run."""

    run: EvidenceRun
    reports: tuple[JUnitReport, ...]
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    @property
    def flaky(self) -> tuple[str, ...]:
        """Ids of tests that passed only after a retry."""
        return tuple(c.id for c in self.run.checks if FLAKY_TAG in c.tags)


# --- parsing --------------------------------------------------------------


class _DoctypeRefused(Exception):
    pass


def _refuse(*_args: object) -> None:
    raise _DoctypeRefused


def _parse_xml(data: bytes) -> ET.Element:
    """Parse with expat directly so DOCTYPEs and entity declarations are refused
    before anything is expanded (the C ElementTree parser can't be hooked)."""
    builder = ET.TreeBuilder()
    parser = pyexpat.ParserCreate()
    parser.StartDoctypeDeclHandler = _refuse
    parser.EntityDeclHandler = _refuse
    parser.StartElementHandler = builder.start
    parser.EndElementHandler = builder.end
    parser.CharacterDataHandler = builder.data
    parser.Parse(data, True)
    return builder.close()


def _read_bytes(path: Path, max_bytes: int) -> bytes:
    if not path.exists():
        raise JUnitInputError(path, "result file not found")
    if not path.is_file():
        raise JUnitInputError(path, "result path is not a file")
    try:
        size = path.stat().st_size
        if size > max_bytes:
            raise JUnitInputError(path, f"result file is {size} bytes, over the {max_bytes} limit")
        data = path.read_bytes()
    except OSError as exc:
        raise JUnitInputError(path, f"result file can't be read ({exc.strerror or exc})") from exc
    if len(data) > max_bytes:  # the file grew after stat()
        raise JUnitInputError(path, f"result file is over the {max_bytes} byte limit")
    if not data.strip():
        raise JUnitInputError(path, "result file is empty")
    return data


def _detect_source(root: ET.Element, path: Path) -> CheckSource:
    if root.tag == "testsuites":
        name = root.get("name")
        if name == "pytest tests":
            return CheckSource.PYTEST
        if name == "vitest tests":
            return CheckSource.VITEST
        if "id" in root.attrib:  # Playwright writes <testsuites id="" name="" ...>
            return CheckSource.PLAYWRIGHT
    if any(suite.get("name") == "pytest" for suite in root.iter("testsuite")):
        return CheckSource.PYTEST
    raise JUnitInputError(
        path,
        "can't tell which tool wrote this file; set its source (pytest, vitest or playwright)",
    )


@dataclass
class _Entry:
    raw_id: str
    name: str
    suite: str | None
    status: CheckStatus
    message: str | None
    duration_ms: float | None


def _message(element: ET.Element) -> str | None:
    text = element.get("message") or (element.text or "")
    text = text.strip()
    if not text:
        return None
    return text if len(text) <= MESSAGE_LIMIT else text[: MESSAGE_LIMIT - 1] + "…"


def _duration_ms(testcase: ET.Element, path: Path, label: str) -> float | None:
    raw = testcase.get("time")
    if raw is None or not raw.strip():
        return None
    try:
        seconds = float(raw)
    except ValueError:
        raise JUnitInputError(path, f"test case {label!r} has time={raw!r}, not a number") from None
    if not math.isfinite(seconds) or seconds < 0:
        raise JUnitInputError(path, f"test case {label!r} has an invalid time={raw!r}")
    return round(seconds * 1000, 3)


def _entry(testcase: ET.Element, suite: str | None, path: Path) -> _Entry:
    name = (testcase.get("name") or "").strip()
    if not name:
        raise JUnitInputError(path, "a <testcase> has no name")
    classname = (testcase.get("classname") or "").strip()
    raw_id = f"{suite or ''}::{classname}::{name}"

    errors = testcase.findall("error")
    failures = testcase.findall("failure")
    skipped = testcase.findall("skipped")
    if errors:
        status, message = CheckStatus.ERROR, _message(errors[-1])
    elif failures:
        status, message = CheckStatus.FAILED, _message(failures[-1])
    elif skipped:
        status, message = CheckStatus.SKIPPED, _message(skipped[-1])
    else:
        status, message = CheckStatus.PASSED, None
    return _Entry(raw_id, name, suite, status, message, _duration_ms(testcase, path, raw_id))


def _collect(element: ET.Element, label: str | None, path: Path, out: list[_Entry]) -> None:
    """Walk a <testsuites>/<testsuite> tree depth-first, appending entries in
    file order, and check each element's ``tests=`` count on the way back up."""
    start = len(out)
    suite = label or (element.get("name") or "").strip() or None
    for child in element:
        if child.tag == "testcase":
            out.append(_entry(child, suite, path))
        elif child.tag == "testsuite":
            _collect(child, label, path, out)
    entries = out[start:]
    _check_count(element, len(entries), len({e.raw_id for e in entries}), path)


def _check_count(element: ET.Element, entries: int, unique: int, path: Path) -> None:
    raw = element.get("tests")
    if raw is None:
        return
    where = (
        f"<testsuite name={element.get('name')!r}>"
        if element.tag == "testsuite"
        else "<testsuites>"
    )
    try:
        declared = int(raw)
    except ValueError:
        raise JUnitInputError(path, f"{where} has tests={raw!r}, not a whole number") from None
    # Not an exact match on purpose: pytest's tests= counts neither the unique
    # tests nor the entries when tests are rerun or fail in teardown. Missing
    # test cases are what matters: fewer entries than declared means the run
    # or the file stopped early.
    if entries < declared:
        raise JUnitInputError(
            path,
            f"{where} declares {declared} tests but contains only {entries} test cases; "
            "the run or the file may have stopped early",
        )
    if unique > declared:
        raise JUnitInputError(
            path, f"{where} declares {declared} tests but contains {unique} different tests"
        )


def _group_attempts(entries: list[_Entry], source: CheckSource) -> list[list[_Entry]]:
    """Group retry attempts. Only pytest writes them as separate entries, always
    one after another; anything else sharing an id is a duplicate."""
    groups: list[list[_Entry]] = []
    for entry in entries:
        if source is CheckSource.PYTEST and groups and groups[-1][-1].raw_id == entry.raw_id:
            groups[-1].append(entry)
        else:
            groups.append([entry])
    return groups


def _duplicate_hint(source: CheckSource) -> str:
    if source is CheckSource.PLAYWRIGHT:
        return (
            " If the same tests run in several Playwright projects, set "
            "includeProjectInTestName: true in the JUnit reporter."
        )
    return ""


def _number_duplicates(
    checks: list[CheckEvidence],
    duplicates: DuplicateIds,
    where: str,
    hint: str = "",
) -> tuple[list[CheckEvidence], list[str]]:
    seen: dict[str, int] = {}
    repeated: list[str] = []
    for check in checks:
        seen[check.id] = seen.get(check.id, 0) + 1
        if seen[check.id] == 2:
            repeated.append(check.id)
    if not repeated:
        return checks, []
    if duplicates is DuplicateIds.ERROR:
        shown = ", ".join(repr(i) for i in repeated[:5])
        more = f" and {len(repeated) - 5} more" if len(repeated) > 5 else ""
        raise JUnitInputError(
            where,
            f"duplicate test ids: {shown}{more}. Two test cases with the same id would hide "
            f"one behind the other.{hint} To keep both, number them (duplicates: number).",
        )
    taken = {c.id for c in checks}
    counter: dict[str, int] = {}
    result: list[CheckEvidence] = []
    warnings: list[str] = []
    for check in checks:
        counter[check.id] = counter.get(check.id, 0) + 1
        if counter[check.id] == 1:
            result.append(check)
            continue
        n = counter[check.id]
        new_id = f"{check.id}#{n}"
        while new_id in taken:
            n += 1
            new_id = f"{check.id}#{n}"
        taken.add(new_id)
        result.append(check.model_copy(update={"id": new_id}))
        warnings.append(f"{where}: duplicate test id {check.id!r} numbered as {new_id!r}")
    return result, warnings


def read_junit(
    spec: JUnitInput,
    *,
    duplicates: DuplicateIds = DuplicateIds.ERROR,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> JUnitReport:
    """Read one JUnit XML file. Raises ``JUnitInputError`` for untrustworthy input."""
    path = Path(spec.path)
    data = _read_bytes(path, max_bytes)
    try:
        root = _parse_xml(data)
    except _DoctypeRefused:
        raise JUnitInputError(
            path, "result file contains a DOCTYPE, which is refused for safety"
        ) from None
    except (pyexpat.ExpatError, ValueError) as exc:
        raise JUnitInputError(path, f"result file is truncated or not valid XML ({exc})") from None
    if root.tag not in ("testsuites", "testsuite"):
        raise JUnitInputError(
            path, f"root element is <{root.tag}>, expected <testsuites> or <testsuite>"
        )

    source = CheckSource(spec.source) if spec.source else _detect_source(root, path)
    entries: list[_Entry] = []
    _collect(root, spec.suite, path, entries)

    checks: list[CheckEvidence] = []
    for attempts in _group_attempts(entries, source):
        final = attempts[-1]
        flaky = len(attempts) > 1 and final.status is CheckStatus.PASSED
        message = final.message or next((a.message for a in reversed(attempts) if a.message), None)
        checks.append(
            CheckEvidence(
                id=final.raw_id,
                name=final.name,
                suite=final.suite,
                source=source,
                status=final.status,
                duration_ms=final.duration_ms,
                message=message,
                tags=[FLAKY_TAG] if flaky else [],
            )
        )
    checks, warnings = _number_duplicates(
        checks, DuplicateIds(duplicates), str(path), _duplicate_hint(source)
    )

    blockers: list[str] = []
    if not checks:
        blockers.append(f"{path}: no test cases found, so nothing ran")
    elif spec.min_checks is not None and len(checks) < spec.min_checks:
        blockers.append(
            f"{path}: {len(checks)} tests found, fewer than min_checks {spec.min_checks}"
        )

    return JUnitReport(
        input=EvidenceInput(format=InputFormat.JUNIT, path=str(spec.path)),
        source=source,
        checks=tuple(checks),
        warnings=tuple(warnings),
        blockers=tuple(blockers),
    )


def import_junit(
    specs: Sequence[JUnitInput] | Iterable[JUnitInput],
    *,
    project: str,
    created_at: datetime | None = None,
    version: str | None = None,
    commit: str | None = None,
    duplicates: DuplicateIds = DuplicateIds.ERROR,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> JUnitImport:
    """Read several JUnit files into one evidence run.

    Any input error stops the import. Ids must also be unique across files;
    give each input its own ``suite`` label when two files could share ids.
    """
    specs = list(specs)
    if not specs:
        raise JUnitInputError("", "no JUnit result files were given")
    reports = [read_junit(s, duplicates=duplicates, max_bytes=max_bytes) for s in specs]

    checks = [c for r in reports for c in r.checks]
    checks, cross_warnings = _number_duplicates(
        checks, DuplicateIds(duplicates), "across result files", " Give each input a suite label."
    )
    run = EvidenceRun(
        project=project,
        version=version,
        commit=commit,
        created_at=created_at or datetime.now(UTC),
        inputs=[r.input for r in reports],
        checks=checks,
    )
    return JUnitImport(
        run=run,
        reports=tuple(reports),
        warnings=tuple(w for r in reports for w in r.warnings) + tuple(cross_warnings),
        blockers=tuple(b for r in reports for b in r.blockers),
    )
