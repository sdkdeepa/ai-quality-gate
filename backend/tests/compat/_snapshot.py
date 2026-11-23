"""Helpers for the M0 compatibility tests.

These tests lock in how the gate behaves *today*, so that later framework
milestones (the `aqg` core, packaging changes) can prove they changed nothing.

- Values that differ on every run (ids, timestamps, trace ids, uptime) are
  replaced with "<volatile>" before comparing; the key itself is kept, so a
  removed or renamed field still fails the test.
- Floats are rounded to 9 decimal places.
- A missing snapshot is a test failure, never silently created. To write or
  intentionally update snapshots, run with UPDATE_SNAPSHOTS=1 and explain the
  change in the PR.
"""

import json
import os
from pathlib import Path
from typing import Any

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"

VOLATILE_KEYS = {
    "id",
    "run_id",
    "decision_id",
    "policy_id",
    "baseline_id",
    "trace_id",
    "request_id",
    "started_at",
    "completed_at",
    "created_at",
    "approved_at",
    "generated_at",
    "timestamp",
    "uptime_seconds",
}


def normalize(value: Any) -> Any:
    """Replace run-specific values so two equivalent runs compare equal."""
    if isinstance(value, dict):
        return {
            key: ("<volatile>" if key in VOLATILE_KEYS and item is not None else normalize(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [normalize(item) for item in value]
    if isinstance(value, float):
        return round(value, 9)
    return value


def shape(value: Any) -> Any:
    """The structure of a JSON value: keys and value types, not the values.

    Lists are described by the merged shape of their items, so a list's length
    can change without failing the contract, but a new, missing or retyped
    field cannot.
    """
    if isinstance(value, dict):
        return {key: shape(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        merged: Any = None
        for item in value:
            merged = _merge(merged, shape(item))
        return [merged] if value else []
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    return type(value).__name__


def _merge(a: Any, b: Any) -> Any:
    if a is None:
        return b
    if isinstance(a, dict) and isinstance(b, dict):
        return {key: _merge(a.get(key), b.get(key)) for key in sorted(set(a) | set(b))}
    if a == b:
        return a
    if a == "null":
        return b
    if b == "null":
        return a
    return f"{a}|{b}" if str(a) < str(b) else f"{b}|{a}"


def assert_snapshot(name: str, data: Any) -> None:
    path = SNAPSHOT_DIR / f"{name}.json"
    text = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return
    assert path.exists(), (
        f"Missing snapshot {path.name}. Run with UPDATE_SNAPSHOTS=1 to create it, "
        "and commit it with an explanation."
    )
    expected = json.loads(path.read_text(encoding="utf-8"))
    assert json.loads(text) == expected, (
        f"Behavior changed from snapshot {path.name}. If this change is intended, "
        "run with UPDATE_SNAPSHOTS=1 and explain why in the PR."
    )
