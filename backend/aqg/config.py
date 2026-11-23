"""quality-gate.yml (M6).

Example::

    version: 1
    project: steplab
    inputs:
      - type: junit
        path: reports/unit.xml          # a path or a glob, relative to this file
        suite: unit                     # optional label, the first part of every id
      - type: junit
        path: reports/e2e/*.xml
        suite: e2e
        min_checks: 3                   # optional: BLOCK if fewer tests are found
    policy:                             # every key is optional; defaults shown
      required: ["e2e::*export*"]
      on_missing: block
      on_skipped: block
      on_error: block
      on_optional_skipped: warn
      on_optional_failed: block
      on_optional_error: block
      on_flaky: warn
      min_pass_rate: null
      fail_on_warn: false
      duplicate_ids: error              # or "number"
      regressions:
        on_new_failure: block
        on_new_failing: block
        on_skipped_required: block
        on_removed_required: block
        on_removed: warn
        on_possible_rename: warn
    baseline:                           # optional; leave out until one is approved
      path: quality/baseline.json
      renames:
        "e2e::old.spec.ts::old name": "e2e::new.spec.ts::new name"
    output:
      dir: aqg-report

The schema is strict: an unknown key is an error, so a typo can't silently
turn a rule off. ``version: 1`` is a contract once v1 is released.
"""

from __future__ import annotations

import glob
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from aqg.baseline import RegressionPolicy
from aqg.evidence import CheckSource
from aqg.evidence.models import NonBlankStr
from aqg.importers import DuplicateIds, JUnitInput, JUnitInputError
from aqg.policy import EvidencePolicy

DEFAULT_CONFIG = "quality-gate.yml"
DEFAULT_OUTPUT_DIR = "aqg-report"
MAX_CONFIG_BYTES = 1024 * 1024
_GLOB_CHARS = set("*?[")


class ConfigError(Exception):
    """quality-gate.yml (or the baseline it points to) can't be used. Exit code 2."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class InputConfig(_Model):
    type: Literal["junit"]
    path: NonBlankStr
    suite: NonBlankStr | None = None
    source: Literal["pytest", "vitest", "playwright"] | None = None
    min_checks: int | None = Field(default=None, ge=1, strict=True)


class PolicyConfig(EvidencePolicy):
    duplicate_ids: DuplicateIds = DuplicateIds.ERROR
    regressions: RegressionPolicy = Field(default_factory=RegressionPolicy)

    def evidence_policy(self) -> EvidencePolicy:
        return EvidencePolicy(
            **self.model_dump(include=set(EvidencePolicy.model_fields), mode="python")
        )


class BaselineConfig(_Model):
    path: NonBlankStr
    renames: dict[NonBlankStr, NonBlankStr] = Field(default_factory=dict)


class OutputConfig(_Model):
    dir: NonBlankStr = DEFAULT_OUTPUT_DIR


class GateConfig(_Model):
    version: Literal[1]
    project: NonBlankStr
    inputs: list[InputConfig] = Field(min_length=1)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)
    baseline: BaselineConfig | None = None
    output: OutputConfig = Field(default_factory=OutputConfig)


class LoadedConfig:
    """A validated config and the folder its relative paths start from."""

    def __init__(self, config: GateConfig, path: Path) -> None:
        self.config = config
        self.path = path
        self.root = path.parent

    def resolve(self, value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else self.root / path

    def display(self, path: str | Path) -> str:
        """A path as people wrote it: relative to the config folder when inside it."""
        path = Path(path)
        try:
            return path.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return str(path)

    @property
    def baseline_path(self) -> Path | None:
        return self.resolve(self.config.baseline.path) if self.config.baseline else None

    @property
    def output_dir(self) -> Path:
        return self.resolve(self.config.output.dir)

    def junit_inputs(self) -> list[JUnitInput]:
        """Expand paths and globs into result files. A glob that matches nothing
        is an input error: a missing report must never look like a pass."""
        specs: list[JUnitInput] = []
        for item in self.config.inputs:
            if _GLOB_CHARS & set(item.path):
                pattern = str(self.resolve(item.path))
                files = sorted(Path(p) for p in glob.glob(pattern, recursive=True))
                files = [f for f in files if f.is_file()]
                if not files:
                    raise JUnitInputError(item.path, "no result files match this pattern")
            else:
                files = [self.resolve(item.path)]
            specs.extend(
                JUnitInput(
                    path=f,
                    suite=item.suite,
                    source=CheckSource(item.source) if item.source else None,
                    min_checks=item.min_checks,
                )
                for f in files
            )
        return specs


def _describe(exc: ValidationError) -> str:
    lines = []
    for error in exc.errors():
        where = ".".join(str(p) for p in error["loc"]) or "(top level)"
        lines.append(f"  {where}: {error['msg']}")
    return "\n".join(lines)


def load_config(path: str | Path = DEFAULT_CONFIG) -> LoadedConfig:
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"{path}: config file not found")
    if path.stat().st_size > MAX_CONFIG_BYTES:
        raise ConfigError(f"{path}: config file is larger than {MAX_CONFIG_BYTES} bytes")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{path}: can't be read ({exc})") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: not valid YAML ({exc})") from exc
    if data is None:
        raise ConfigError(f"{path}: config file is empty")
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: expected a mapping of settings at the top level")
    try:
        config = GateConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"{path}: invalid config\n{_describe(exc)}") from exc
    return LoadedConfig(config, path.resolve())
