"""M1: the committed schema.json must match the model.

schema.json ships inside the package so other tools can validate evidence files
without Python. It is generated from the model, never edited by hand. To
regenerate it on purpose (and explain why in the PR):

    UPDATE_SNAPSHOTS=1 uv run pytest tests/aqg/test_evidence_schema.py
"""

import json
import os
from pathlib import Path

import jsonschema

import aqg.evidence
from aqg.evidence import evidence_run_json_schema

SCHEMA_PATH = Path(aqg.evidence.__file__).parent / "schema.json"


def _render(schema: dict) -> str:
    return json.dumps(schema, indent=2, ensure_ascii=False) + "\n"


def test_saved_schema_matches_model():
    expected = evidence_run_json_schema()
    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        SCHEMA_PATH.write_text(_render(expected), encoding="utf-8")
    assert SCHEMA_PATH.exists(), (
        f"{SCHEMA_PATH} is missing; generate it with UPDATE_SNAPSHOTS=1 and commit it"
    )
    saved = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert saved == expected, (
        "schema.json is out of date with aqg/evidence/models.py; regenerate it with "
        "UPDATE_SNAPSHOTS=1 and explain the change in the PR"
    )
    text = SCHEMA_PATH.read_text(encoding="utf-8")
    assert text == _render(saved), "schema.json is not normalized"


def test_saved_schema_is_valid_json_schema():
    saved = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(saved)


def test_schema_accepts_model_output_and_rejects_bad_status():
    saved = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(saved)
    doc = {
        "schema_version": "1",
        "project": "steplab",
        "created_at": "2026-11-23T08:00:00Z",
        "inputs": [{"format": "junit", "path": "reports/unit.xml"}],
        "checks": [
            {"id": "u::a::b", "name": "b", "source": "pytest", "status": "passed"},
        ],
    }
    assert list(validator.iter_errors(doc)) == []
    doc["checks"][0]["id"] = "x"
    assert list(validator.iter_errors(doc)) == []

    for field, bad in [("status", "flaky"), ("id", ""), ("id", "  "), ("id", " a"), ("x", 1)]:
        broken = json.loads(json.dumps(doc))
        broken["checks"][0][field] = bad
        assert list(validator.iter_errors(broken)), f"{field}={bad!r} must fail schema validation"
